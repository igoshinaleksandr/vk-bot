# VK-бот приветствия новых участников

Бот для сообщества VK: при вступлении нового пользователя автоматически
оставляет комментарий с упоминанием этого человека под закреплённым постом.
Развёрнут в Kubernetes (k3s) на домашнем homelab (Proxmox), с раздельными
test/prod окружениями и доступом снаружи через Cloudflare Tunnel.

## Архитектура

```
VK Callback API
      │
      ▼
Cloudflare Tunnel (постоянный HTTPS-адрес на собственном домене)
      │
      ▼
k3s NodePort Service
      │
      ▼
Deployment (aiohttp-приложение в Docker-контейнере)
      │
      ▼
VK API (users.get, wall.createComment)
```

**Инфраструктура:**
- 2-нодовый k3s-кластер (`k3s-master` + `k3s-worker`) в Proxmox
- Docker-образ бота собирается на `k3s-master`, публикуется в Docker Hub
- Test и prod — полностью изолированные Kubernetes-namespace
  (`vk-bot-test`, `vk-bot-prod`), каждый со своим Secret, Deployment, Service
- Один Cloudflare Tunnel маршрутизирует оба поддомена
  (`vk-bot-test.<домен>` и `vk-bot.<домен>`) на соответствующие NodePort
- Секреты (токены VK) живут только в Kubernetes Secret, не в git

## Структура репозитория

```
vk-bot/
  bot.py              — код бота (aiohttp-сервер)
  requirements.txt
  Dockerfile
  .env.example         — шаблон переменных окружения для локального запуска
  k8s/
    test/deployment.yaml   — Namespace + Deployment + Service (тест)
    prod/deployment.yaml   — Namespace + Deployment + Service (прод)
```

## Как это работает

1. VK при вступлении нового пользователя (`type: group_join`) шлёт POST-запрос
   на адрес, указанный в настройках Callback API сообщества.
2. Бот получает имя пользователя через `users.get` и оставляет комментарий
   через `wall.createComment` под постом с ID из `WALL_POST_ID`.
3. Дедупликация по `event_id` — VK может слать повторные запросы, если не
   получил ответ вовремя; бот не публикует комментарий дважды.

## Локальный запуск (без Docker/Kubernetes)

```bash
pip install -r requirements.txt --break-system-packages
cp .env.example .env
# заполнить .env реальными значениями тестового сообщества
export $(cat .env | xargs)
python bot.py
curl http://localhost:8080/health
```

## Сборка и публикация образа

```bash
docker build -t <логин_dockerhub>/vk-bot:latest .
docker login
docker push <логин_dockerhub>/vk-bot:latest
```

## Деплой в кластер

Секреты создаются отдельно от манифестов (не хранятся в git):

```bash
kubectl create namespace vk-bot-test

kubectl create secret generic vk-bot-secrets \
  --namespace=vk-bot-test \
  --from-literal=VK_TOKEN="токен_сообщества" \
  --from-literal=VK_GROUP_ID="id_сообщества" \
  --from-literal=VK_CONFIRMATION_TOKEN="строка_из_настроек_callback_api" \
  --from-literal=VK_SECRET_KEY="секретный_ключ" \
  --from-literal=WALL_POST_ID="номер_поста"

kubectl apply -f k8s/test/deployment.yaml
kubectl -n vk-bot-test get pods
```

Аналогично для `vk-bot-prod` с боевыми значениями и `k8s/prod/deployment.yaml`.

## Обновление Secret (например, при ротации токена)

Точечное обновление одного поля без пересоздания всего Secret:

```bash
kubectl patch secret vk-bot-secrets -n vk-bot-test \
  --type='json' \
  -p="[{\"op\": \"replace\", \"path\": \"/data/VK_TOKEN\", \"value\": \"$(echo -n 'новое_значение' | base64)\"}]"

kubectl rollout restart deployment vk-bot -n vk-bot-test
```

## Доступ снаружи — Cloudflare Tunnel

Оба окружения проксируются через один именованный туннель на собственном
домене (конфиг на `k3s-master`, `/etc/cloudflared/config.yml`):

```yaml
tunnel: vk-bot
credentials-file: /etc/cloudflared/<UUID>.json
ingress:
  - hostname: vk-bot-test.<домен>
    service: http://localhost:<NodePort теста>
  - hostname: vk-bot.<домен>
    service: http://localhost:<NodePort прода>
  - service: http_status:404
```

Работает как systemd-служба (`cloudflared`), переживает перезагрузку сервера.

## Планы на будущее

- Перейти на Helm-чарт вместо голых манифестов
- Шифрование секретов в git через Sealed Secrets / SOPS
