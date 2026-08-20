import logging
import os

from aiohttp import web, ClientSession

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("vk-bot")

VK_TOKEN = os.environ["VK_TOKEN"]
VK_GROUP_ID = os.environ["VK_GROUP_ID"]
VK_CONFIRMATION_TOKEN = os.environ["VK_CONFIRMATION_TOKEN"]
VK_SECRET_KEY = os.environ.get("VK_SECRET_KEY", "")
WALL_POST_ID = os.environ["WALL_POST_ID"]
PORT = int(os.environ.get("PORT", "8080"))

VK_API_VERSION = "5.199"
VK_API_URL = "https://api.vk.com/method"

_processed_events = set()


async def vk_api_call(session, method, **params):
    params.update({"access_token": VK_TOKEN, "v": VK_API_VERSION})
    async with session.post(f"{VK_API_URL}/{method}", data=params) as resp:
        data = await resp.json()
        if "error" in data:
            log.error("Ошибка VK API (%s): %s", method, data["error"])
        return data


async def get_user_name(session, user_id):
    data = await vk_api_call(session, "users.get", user_ids=user_id)
    response = data.get("response")
    if not response:
        return "друг"
    return response[0]["first_name"]


async def welcome_new_member(session, user_id):
    first_name = await get_user_name(session, user_id)
    mention = f"[id{user_id}|{first_name}]"
    message = f"Привет, {mention}! Добро пожаловать 🤗 Если захочешь обсудить эскиз — я на связи: vk.me/kris.tatts"

    result = await vk_api_call(
        session,
        "wall.createComment",
        owner_id=f"-{VK_GROUP_ID}",
        post_id=WALL_POST_ID,
        message=message,
    )
    if "response" in result:
        log.info("Оставлен комментарий для user_id=%s", user_id)
    else:
        log.warning("Не удалось оставить комментарий для user_id=%s: %s", user_id, result)


async def handle_webhook(request):
    body = await request.json()

    if VK_SECRET_KEY and body.get("secret") != VK_SECRET_KEY:
        log.warning("Неверный secret key в запросе")
        return web.Response(text="ok")

    event_type = body.get("type")

    if event_type == "confirmation":
        return web.Response(text=VK_CONFIRMATION_TOKEN)

    event_id = body.get("event_id", "")
    if event_id in _processed_events:
        return web.Response(text="ok")
    _processed_events.add(event_id)

    if event_type == "group_join":
        user_id = body["object"]["user_id"]
        log.info("Новый участник: user_id=%s", user_id)
        async with ClientSession() as session:
            await welcome_new_member(session, user_id)

    return web.Response(text="ok")


async def health(request):
    return web.Response(text="alive")


def build_app():
    app = web.Application()
    app.router.add_post("/webhook", handle_webhook)
    app.router.add_get("/health", health)
    return app


if __name__ == "__main__":
    web.run_app(build_app(), host="0.0.0.0", port=PORT)
