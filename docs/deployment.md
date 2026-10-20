# Серверный запуск с HTTPS

Конфигурация рассчитана на демонстрационный VPS с Docker Compose и доменом `biom.cloud-path.ru`. Используются синтетические данные. Текущая конфигурация проверена локально с отдельной БД, HTTPS и локальным центром сертификации. Выпуск публичного сертификата, DNS, запуск на VPS и восстановление после перезагрузки хоста ещё не проверены.

## Подготовка сервера

Стартовый ориентир: 2 vCPU, 4 ГБ RAM, 40–60 ГБ SSD, без GPU. Это оценка для демонстрации без локальной LLM, а не результат нагрузочного теста. Сборка образов требует дополнительной памяти и свободного места.

1. Установите Docker Engine и плагин Docker Compose по [официальной инструкции Docker](https://docs.docker.com/engine/install/) для своей ОС. Нужна поддержка `docker compose up --wait`.
2. На Linux с systemd включите автозапуск Docker: `sudo systemctl enable --now docker`. Проверьте `docker version` и `docker compose version`.
3. Разрешите входящие TCP 80/443 в межсетевом экране VPS и панели провайдера, а также SSH для администрирования. Порты 80/443 должны быть свободны; исходящие DNS и HTTPS необходимы для получения образов и сертификатов.
4. Создайте A-запись `biom.cloud-path.ru`, указывающую на будущий публичный IPv4 сервера. AAAA добавляйте только при работающем IPv6 и открытых портах по IPv6; удалите неверную AAAA. Дождитесь обновления DNS.
5. Получите конкретную проверенную ревизию проекта. Конфигурация пока подготовлена локально: её публикация в репозитории или передача проверенного архива — отдельная предпосылка. Не предполагается, что она уже доступна на GitHub. Запишите SHA полученной версии и работайте из корня проекта.

## Настройка окружения

Для отдельного стенда используйте отдельный каталог и Compose-проект. Не запускайте его поверх рабочего локального окружения. Пример задаёт постоянное имя проекта через `COMPOSE_PROJECT_NAME` в `.env.deploy`; при обновлении сохраняйте это имя и каталог.

Создайте закрытый файл из примера, затем сгенерируйте два разных пароля без передачи секретов в аргументах процессов:

```sh
umask 077
cp .env.deploy.example .env.deploy
chmod 600 .env.deploy
python3 - <<'PY'
from pathlib import Path
import secrets

path = Path('.env.deploy')
text = path.read_text()
for key in ('POSTGRES_PASSWORD', 'DEMO_PASSWORD'):
    text = text.replace(f'{key}=\n', f'{key}={secrets.token_hex(24)}\n')
path.write_text(text + 'COMPOSE_PROJECT_NAME=credit-cabinet-vps\n')
PY
```

Эту генерацию выполняют один раз на новом стенде. Проверьте файл в редакторе: домен должен содержать только имя хоста без схемы и пути. Не публикуйте `.env.deploy` и не выводите раскрытую конфигурацию в общий лог. Hex-пароль БД безопасно включается в `DATABASE_URL` без проблем с зарезервированными символами URL. Если выбираете пароль вручную, для БД используйте только hex-символы. `POSTGRES_PASSWORD` и `DEMO_PASSWORD` обязательны: Compose останавливается при пустых значениях.

Серверный файл Compose принудительно задаёт `COOKIE_SECURE=true`. До первого заполнения БД задайте пароль демонстрационных аккаунтов и передайте его участникам отдельно. При обновлении сохраняйте файл, имя проекта, DB/user, пароль существующей БД и тома. Изменение `POSTGRES_PASSWORD` в файле не меняет пароль уже созданного пользователя PostgreSQL; изменение `DEMO_PASSWORD` не меняет пароли аккаунтов после seed.

## Первый запуск

Во всех командах используется сочетание основного файла и серверного дополнения:

```sh
docker compose --env-file .env.deploy -f compose.yaml -f compose.deploy.yaml config --quiet
docker compose --env-file .env.deploy -f compose.yaml -f compose.deploy.yaml up --build -d --wait
docker compose --env-file .env.deploy -f compose.yaml -f compose.deploy.yaml exec backend uv run python -m app.seed
docker compose --env-file .env.deploy -f compose.yaml -f compose.deploy.yaml ps
```

Backend применяет миграции при запуске. Seed создаёт аккаунты из [README](../README.md#демонстрационные-учётные-записи); пароль — значение `DEMO_PASSWORD`. Повторный seed сохраняет существующие данные и пароли. Успешный `up --wait` подтверждает состояние контейнеров, но сам по себе не подтверждает получение публичного сертификата.

Caddy получает `APP_DOMAIN` внутри контейнера, принимает TCP 80/443, автоматически выпускает сертификат и перенаправляет HTTP на HTTPS. Сертификаты и состояние Caddy хранятся в томах `caddy_data` и `caddy_config`, данные PostgreSQL — в `postgres_data`. Все сервисы имеют `restart: unless-stopped`; ручная остановка сервиса отменяет автоматический запуск до следующего запуска. Логи каждого контейнера ограничены тремя файлами по 10 МБ.

Пути `/api` и `/api/*` идут напрямую в `backend:8000` без изменения URI; остальные запросы идут во frontend, где nginx обслуживает также SPA-ссылки. Так API получает Host и HTTPS-схему непосредственно от Caddy. Caddy по умолчанию заменяет входящие пользовательские `X-Forwarded-*`, не доверяя им. Uvicorn принимает заголовки прокси из Docker-сети (`FORWARDED_ALLOW_IPS=*`); это допустимо только при отсутствии внешнего порта backend и доверенных контейнерах сети. Не добавляйте публикацию порта 8000. Порт БД и admin API Caddy также не публикуются. Существующий frontend-порт `127.0.0.1:8080` доступен только на самом сервере, внешний доступ проходит через Caddy.

## Проверка после запуска

На машине с доверенным системным хранилищем сертификатов:

```sh
curl --fail --head http://biom.cloud-path.ru
curl --fail https://biom.cloud-path.ru/api/v1/health
curl --fail --head https://biom.cloud-path.ru
curl --fail --head https://biom.cloud-path.ru/applications/example
```

Первый запрос должен вернуть перенаправление на `https://biom.cloud-path.ru/`, health — успешный JSON, страница и SPA-ссылка — HTML. Не отключайте проверку TLS. Если выбран другой домен, замените его в проверках.

В браузере откройте HTTPS-адрес, войдите клиентом, создайте и повторно откройте черновик; отдельно проверьте вход сотрудником. В инструментах разработчика у cookie сессии должны быть `Secure` и `HttpOnly`. API перед изменяющим запросом выдаёт CSRF-токен через `/api/v1/auth/csrf`; cookie и заголовок `X-CSRF-Token` обязательны, вход обновляет токен. Перезапустите backend и убедитесь, что черновик и сессия сохранились:

```sh
docker compose --env-file .env.deploy -f compose.yaml -f compose.deploy.yaml restart backend
```

После согласованной перезагрузки VPS отдельно проверьте доступность HTTPS и сохранность данных. Локальный тест не заменяет эту проверку.

## Обновление и резервная копия

Перед обновлением согласуйте окно недоступности, запишите текущую ревизию (`git rev-parse HEAD`) и подготовьте конкретную следующую проверенную ревизию. Не обновляйтесь вслепую до вершины ветки. При изменениях схемы учитывайте совместимость и прекратите запись, остановив frontend, Caddy и backend перед резервным копированием; БД продолжает работать:

```sh
docker compose --env-file .env.deploy -f compose.yaml -f compose.deploy.yaml stop caddy frontend backend
umask 077
mkdir -p /srv/credit-cabinet-backups
chmod 700 /srv/credit-cabinet-backups
backup_file="/srv/credit-cabinet-backups/database-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose --env-file .env.deploy -f compose.yaml -f compose.deploy.yaml exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup_file" || {
  echo "Ошибка pg_dump: обновление остановлено" >&2
  exit 1
}
test -s "$backup_file" || exit 1
```

Используйте доступный вам закрытый каталог вне репозитория; при необходимости создайте его с администратором. Проверьте успешный код завершения `pg_dump` до перехода дальше: наличие файла само по себе не доказывает пригодность копии. Скопируйте backup на отдельное хранилище с ограниченным доступом и отдельно проверьте восстановление в тестовую БД.

Это логическая копия БД, а не резервная копия всего сервера: она не включает `.env.deploy`, сертификаты Caddy, код или будущие файлы документов. Закрытую копию окружения, постоянных файлов и необходимые серверные настройки храните отдельно. Резервную копию БД делайте до запуска новой версии, потому что backend автоматически применяет миграции.

Получите заранее проверенный SHA из опубликованного репозитория или проверенного архива. Для Git после получения нужной ревизии выполните `git checkout <проверенный-SHA>`, затем:

```sh
docker compose --env-file .env.deploy -f compose.yaml -f compose.deploy.yaml config --quiet
docker compose --env-file .env.deploy -f compose.yaml -f compose.deploy.yaml up --build -d --wait
docker compose --env-file .env.deploy -f compose.yaml -f compose.deploy.yaml ps
```

Повторите HTTPS-сценарий и проверку сохранённых данных. Не удаляйте тома при обновлении. Возврат к старому коду не гарантирует совместимость с новой схемой БД; автоматический безопасный откат миграций не предусмотрен. При неудаче остановите запись, сохраните логи и решите, нужна ли исправленная версия или проверенное восстановление backup с потерей изменений после его создания.

## Диагностика

```sh
docker compose --env-file .env.deploy -f compose.yaml -f compose.deploy.yaml logs --tail 100 caddy backend db
docker compose --env-file .env.deploy -f compose.yaml -f compose.deploy.yaml ps
docker compose --env-file .env.deploy -f compose.yaml -f compose.deploy.yaml exec caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

При ошибке сертификата проверьте A/AAAA, доступность TCP 80/443 извне и логи Caddy; не повторяйте получение сертификата в цикле. При недоступности API проверьте health backend и миграции, затем доступность БД. Логи и backup могут содержать данные: перед передачей удаляйте секреты. Для временной остановки используйте `stop`, для запуска — `up -d --wait` с теми же двумя Compose-файлами и `.env.deploy`.
