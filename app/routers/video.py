import asyncio
import os
import re
import shutil
import time
import aiofiles
import cv2

from multiprocessing import Process
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    UploadFile,
    BackgroundTasks,
    status,
)
from firebase_admin import messaging
from app import db
from app import supabase
from app.dependencies import get_current_user
from app.routers.image import inferenceImage
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore import ArrayUnion
from app import logger
from custom_utils import utils
router = APIRouter(prefix="/video", tags=["Video"])


@router.post("")
async def handleVideoRequest(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    threshold: float = 0.3,
    user=Depends(get_current_user)
):
    if re.search("^video\/", file.content_type) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be video",
        )

    try:
        id = str(now())
        _, artifact_ref = db.collection("artifacts").add(
            {"name": id + ".mp4", "status": "pending"}
        )
        db.collection("user").document(user["sub"]).update({"artifacts": ArrayUnion(['artifact/' + artifact_ref.id])})
        os.mkdir(id)
        async with aiofiles.open(os.path.join(id, "input.mp4"), "wb") as out_file:
            while content := await file.read(102400):
                await out_file.write(content)
        background_tasks.add_task(inferenceVideo, artifact_ref.id, id, threshold)
        return id + ".mp4"
    except ValueError as err:
        logger.error(err)
        shutil.rmtree(id)


def now():
    return round(time.time() * 1000)


def createThumbnail(thumbnail, inputDir):
    thumbnail = cv2.resize(
        src=thumbnail, dsize=(160, 160), interpolation=cv2.INTER_AREA
    )
    cv2.imwrite(os.path.join(inputDir, "thumbnail.jpg"), thumbnail)


def inferenceFrame(inputDir, threshold: float = 0.3):
    cap = cv2.VideoCapture(
        filename=os.path.join(inputDir, "input.mp4"), apiPreference=cv2.CAP_FFMPEG
    )
    fps = cap.get(cv2.CAP_PROP_FPS)
    size = (
        int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    )
    result = cv2.VideoWriter(
        filename=os.path.join(inputDir, "out.mp4"),
        fourcc=cv2.VideoWriter_fourcc(*"mp4v"),
        fps=fps,
        frameSize=size,
    )

    isFirstFrame = True
    thumbnail = None
    while cap.isOpened():
        res, frame = cap.read()
        if isFirstFrame:
            isFirstFrame = False
            thumbnail = frame

        if res == False:
            break

        resFram = inferenceImage(frame, threshold, False)
        result.write(resFram)
    cap.release()
    result.release()
    del cap
    del result
    return thumbnail


async def inferenceVideo(artifactId: str, inputDir: str, threshold: float):
    logger.info("Start inference video")
    try:
        Process(updateArtifact(artifactId, {"status": "processing"})).start()
        thumbnail = inferenceFrame(inputDir, threshold=threshold)
        createThumbnail(thumbnail, inputDir)

        async def uploadVideo():
            async with aiofiles.open(os.path.join(inputDir, "out.mp4"), "rb") as f:
                supabase.storage.from_("video").upload(
                    inputDir + ".mp4", await f.read(), {"content-type": "video/mp4"}
                )

        async def uploadThumbnail():
            async with aiofiles.open(
                os.path.join(inputDir, "thumbnail.jpg"), "rb"
            ) as f:
                supabase.storage.from_("thumbnail").upload(
                    inputDir + ".jpg", await f.read(), {"content-type": "image/jpeg"}
                )

        try:
            n = now()
            _, _ = await asyncio.gather(uploadVideo(), uploadThumbnail())
            print(now() - n)
        except Exception as e:
            logger.error(e)

        updateArtifact(
            artifactId,
            {
                "status": "success",
                "path": "https://hdfxssmjuydwfwarxnfe.supabase.co/storage/v1/object/public/video/"
                + inputDir
                + ".mp4",
                "thumbnailURL": "https://hdfxssmjuydwfwarxnfe.supabase.co/storage/v1/object/public/thumbnail/"
                + inputDir
                + ".jpg",
            },
        )
    except:
        Process(
            updateArtifact(
                artifactId,
                {
                    "status": "fail",
                },
            )
        ).start()
    finally:
        try:
            shutil.rmtree(inputDir)
        except PermissionError as e:
            print(e)


def updateArtifact(artifactId: str, body):
    artifact_ref = db.collection("artifacts").document(artifactId)
    artifact_snapshot = artifact_ref.get()
    if artifact_snapshot.exists:
        artifact_ref.update(body)
    utils.sendMessage(artifactId)