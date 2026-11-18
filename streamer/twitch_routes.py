"""
The Twitch settings window's sign-in to Twitch, for the title from what's printing (twitch_title.py), under
/api/stream/twitch. The application's secret and the sign-in's tokens go in and never come back out.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from . import twitch_title
from .errors import answer_errors
from .store import Store, store

router = APIRouter(prefix="/api/stream/twitch", tags=["twitch"])


def get_db() -> Store:
    return store()


class TwitchAppIn(BaseModel):
    """The Twitch application the plugin signs in through (dev.twitch.tv). Anything left out stays as it was."""

    client_id: str | None = Field(None, max_length=100)  # "": forgotten, with the sign-in
    client_secret: str | None = Field(None, max_length=100)  # set it; null or "" leaves the saved one alone
    clear_secret: bool = False


@router.get("")
def twitch_page(db: Store = Depends(get_db)):
    """{client_id, secret_set, signed_in_as, signing_in: {code, url, expires_at} | null, sign_in_error, title: {title,
    at, error}}"""
    return twitch_title.page(db)


@router.put("/app")
def save_app(payload: TwitchAppIn, db: Store = Depends(get_db)):
    with answer_errors():
        twitch_title.save_app(db, payload.client_id, payload.client_secret, payload.clear_secret)
    return twitch_title.page(db)


@router.post("/sign-in")
def start_sign_in(db: Store = Depends(get_db)):
    """Start signing in: the page shows the code to type on twitch.tv/activate, and the plugin picks it up."""
    with answer_errors():
        twitch_title.sign_in.start(db)
    return twitch_title.page(db)


@router.post("/sign-in/cancel")
def cancel_sign_in(db: Store = Depends(get_db)):
    twitch_title.sign_in.cancel()
    return twitch_title.page(db)


@router.post("/sign-out")
def sign_out(db: Store = Depends(get_db)):
    twitch_title.sign_out(db)
    return twitch_title.page(db)


@router.post("/title")
def set_title_now(db: Store = Depends(get_db)):
    """Set the title from what's printing on Twitch now (live or not): what the window's Set title now does."""
    with answer_errors():
        if not twitch_title.app(db)["client_id"] or not twitch_title.page(db)["signed_in_as"]:
            raise ValueError("Sign in to Twitch first.")
        twitch_title.keeper.check(db, force=True)
    return twitch_title.page(db)
