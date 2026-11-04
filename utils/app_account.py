"""Удаление аккаунта приложения по просьбе пользователя (AVG/GDPR; обязательно для App Store и Google Play).

POST /api/app/me/delete {"confirm": true}

Что происходит:
- личные данные аккаунта стираются: почта, телефон, Telegram, имя, @username, фото, обложка, «о себе», город, координаты;
- всё, что человек публиковал, удаляется: посты с фото, лайками и комментариями, истории, клипы, объявления
  барахолки, сообщения в чатах, комментарии и реакции под чужими публикациями, избранное, дружбы и заявки;
- все сеансы завершаются, старые токены перестают работать;
- платежи остаются: их записи нужны для бухгалтерии (закон требует хранить 7 лет), в них нет личных данных, кроме id;
- заказы магазина остаются на те же 7 лет (документы учёта), но отвязываются от аккаунта; push-токены его устройств выключаются;
- личные сообщения собеседникам остаются у собеседников, но автор показывается как «Удалённый аккаунт».

Строка app_users сохраняется пустой, чтобы ссылки на id в чужих данных не указывали на чужой новый аккаунт.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiohttp import web
from sqlalchemy import delete, or_, select, update

from database.db import get_session
from database.models import (AppFavorite, AppPushToken, ShopOrder, AppSession, AppUser, ChatMessage, Friendship, ItemComment, ItemLike, Listing,
                             MarketItem, MarketPhoto, PostComment, PostLike, PostPhoto, PulseClip, PulseComment, PulseLike,
                             PulseSave, Story, StoryReaction, UserPost)
from utils.site_api import _body, _err, _json

log = logging.getLogger(__name__)

DELETED_NAME = "Удалённый аккаунт"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def wipe_user(session, u: AppUser) -> None:
    """Стереть личные данные и публикации аккаунта. Коммит делает вызывающий."""
    uid = u.id
    post_ids = select(UserPost.id).where(UserPost.user_id == uid)
    item_ids = select(MarketItem.id).where(MarketItem.user_id == uid)
    story_ids = select(Story.id).where(Story.user_id == uid)
    clip_ids = select(PulseClip.id).where(PulseClip.user_id == uid)
    # сначала дочерние записи публикаций (внешних ключей у них нет, иначе останутся «сироты»)
    await session.execute(delete(PostPhoto).where(PostPhoto.post_id.in_(post_ids)))
    await session.execute(delete(PostLike).where(or_(PostLike.post_id.in_(post_ids), PostLike.user_id == uid)))
    await session.execute(delete(PostComment).where(or_(PostComment.post_id.in_(post_ids), PostComment.user_id == uid)))
    await session.execute(delete(MarketPhoto).where(MarketPhoto.item_id.in_(item_ids)))
    await session.execute(delete(StoryReaction).where(or_(StoryReaction.story_id.in_(story_ids), StoryReaction.user_id == uid)))
    await session.execute(delete(PulseLike).where(or_(PulseLike.clip_id.in_(clip_ids), PulseLike.user_id == uid)))
    await session.execute(delete(PulseSave).where(or_(PulseSave.clip_id.in_(clip_ids), PulseSave.user_id == uid)))
    await session.execute(delete(PulseComment).where(or_(PulseComment.clip_id.in_(clip_ids), PulseComment.user_id == uid)))
    for model in (UserPost, MarketItem, Story, PulseClip, ChatMessage, ItemLike, ItemComment, AppFavorite):
        await session.execute(delete(model).where(model.user_id == uid))
    await session.execute(delete(Friendship).where(or_(Friendship.user_id == uid, Friendship.friend_id == uid)))
    await session.execute(update(Listing).where(Listing.app_user_id == uid).values(app_user_id=None))
    # заказы остаются для бухгалтерии (7 лет), но больше не связаны с аккаунтом; уведомления на его устройства выключаются
    await session.execute(update(ShopOrder).where(ShopOrder.app_user_id == uid).values(app_user_id=None))
    await session.execute(update(AppPushToken).where(AppPushToken.app_user_id == uid).values(app_user_id=None, active=False))
    await session.execute(update(AppSession).where(AppSession.user_id == uid).values(revoked=True))
    u.email = u.phone = u.tg_id = u.username = None
    u.name, u.bio, u.city = DELETED_NAME, "", ""
    u.avatar, u.avatar_v, u.cover, u.cover_v = None, 0, None, 0
    u.lat = u.lng = u.geo_at = None
    u.is_private, u.is_verified, u.verified_until = True, False, None
    u.sessions_reset_at = _now()


async def delete_account(request: web.Request) -> web.Response:
    from utils.app_api import _user   # здесь, чтобы не было циклического импорта
    data = await _body(request)
    if data.get("confirm") is not True:
        return _err(request, "Подтвердите удаление аккаунта.")
    async with get_session() as session:
        u = await _user(request, session)
        if not u:
            return _err(request, "Войдите заново.", 401)
        uid = u.id
        await wipe_user(session, u)
        await session.commit()
    from utils import realtime
    await realtime.close_sessions(uid, keep="\0")   # закрыть все живые соединения аккаунта
    log.info("app account %s deleted by user", uid)
    return _json(request, {"ok": True})


def install_routes(app: web.Application) -> None:
    app.router.add_post("/api/app/me/delete", delete_account)
