#!/usr/bin/env bash
#
# Резервная копия базы Matchi в формате custom (-Fc).
#
# Доступы берутся из .env в корне проекта (переменные окружения имеют приоритет),
# пароль передаётся только через PGPASSWORD в окружении процесса: аргументы
# командной строки видны всем в `ps`.
#
# Дамп сначала пишется во временный файл, потом проверяется `pg_restore --list`
# и только затем получает финальное имя. Битый или пустой дамп до каталога
# бэкапов не доходит: ложная уверенность в бэкапе хуже его отсутствия.
#
# Код выхода: 0 — бэкап снят и проверен, 1 — любая ошибка.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${PROJECT_DIR}/.env}"

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

die() {
    printf '[%s] ОШИБКА: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
    exit 1
}

# Значение переменной из .env. Файл не выполняется (в нём пароль и токен,
# а `source` выполнил бы любую строку), а разбирается построчно.
env_file_get() {
    local key="$1" line value
    [ -f "${ENV_FILE}" ] || return 0
    line="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "${ENV_FILE}" | tail -n 1)" || true
    [ -n "${line}" ] || return 0
    value="${line#*=}"
    value="${value%$'\r'}"
    # Обрезать окружающие кавычки, если они есть.
    if [ ${#value} -ge 2 ]; then
        case "${value}" in
            \"*\") value="${value:1:${#value}-2}" ;;
            \'*\') value="${value:1:${#value}-2}" ;;
        esac
    fi
    printf '%s' "${value}"
}

# Приоритет: окружение → .env → значение по умолчанию.
resolve() {
    local name="$1" default="${2-}" value
    value="${!name-}"
    if [ -n "${value}" ]; then
        printf '%s' "${value}"
        return 0
    fi
    value="$(env_file_get "${name}")"
    if [ -n "${value}" ]; then
        printf '%s' "${value}"
        return 0
    fi
    printf '%s' "${default}"
}

require() {
    local name="$1" value
    value="$(resolve "${name}")"
    [ -n "${value}" ] || die "не задано ${name} — ни в окружении, ни в ${ENV_FILE}"
    printf '%s' "${value}"
}

# Порт, хост, база и пользователь обязательны: значения по умолчанию здесь
# опасны. В частности порт 5432 на этой машине занят SSH-туннелем к чужой базе.
DB_USER="$(require DB_USER)"
DB_HOST="$(require DB_HOST)"
DB_PORT="$(require DB_PORT)"
DB_NAME="$(require DB_NAME)"
DB_PASSWORD="$(resolve DB_PASSWORD)"

# Значения по умолчанию совпадают с config/settings.py.
BACKUP_DIR="$(resolve BACKUP_DIR "${HOME}/.local/share/matchi-backups")"
BACKUP_KEEP="$(resolve BACKUP_KEEP 14)"
PG_BIN_DIR="$(resolve PG_BIN_DIR /usr/lib/postgresql/16/bin)"

case "${BACKUP_KEEP}" in
    ''|*[!0-9]*) die "BACKUP_KEEP должен быть целым числом, получено: ${BACKUP_KEEP}" ;;
esac
[ "${BACKUP_KEEP}" -ge 1 ] || die "BACKUP_KEEP должен быть не меньше 1, получено: ${BACKUP_KEEP}"

case "${DB_PORT}" in
    ''|*[!0-9]*) die "DB_PORT должен быть целым числом, получено: ${DB_PORT}" ;;
esac
if [ "${DB_PORT}" = "5432" ]; then
    log "ВНИМАНИЕ: порт 5432. На машине разработки он занят SSH-туннелем к чужой базе,"
    log "         локальный кластер Matchi слушает 5433. Проверьте DB_PORT."
fi

PG_DUMP="${PG_BIN_DIR}/pg_dump"
PG_RESTORE="${PG_BIN_DIR}/pg_restore"
[ -x "${PG_DUMP}" ] || die "не найден ${PG_DUMP} (PG_BIN_DIR=${PG_BIN_DIR}); серверных бинарников PostgreSQL нет в PATH, путь задаётся настройкой PG_BIN_DIR"
[ -x "${PG_RESTORE}" ] || die "не найден ${PG_RESTORE} (PG_BIN_DIR=${PG_BIN_DIR})"

mkdir -p "${BACKUP_DIR}" || die "не удалось создать каталог ${BACKUP_DIR}"
# Дамп содержит персональные данные пользователей — каталог только для владельца.
chmod 700 "${BACKUP_DIR}" 2>/dev/null || true
[ -w "${BACKUP_DIR}" ] || die "каталог ${BACKUP_DIR} недоступен для записи"

STAMP="$(date '+%Y%m%d-%H%M%S')"
TARGET="${BACKUP_DIR}/${DB_NAME}-${STAMP}.dump"
PARTIAL="${TARGET}.part"

# Недоснятый дамп не должен остаться в каталоге бэкапов и выглядеть готовым.
trap 'rm -f "${PARTIAL}" "${PARTIAL}.err" "${PARTIAL}.list"' EXIT

if [ -e "${TARGET}" ]; then
    die "файл ${TARGET} уже существует, бэкап не перезаписываем"
fi

# Пароль — только в окружении процесса, не в аргументах: аргументы видны в `ps`.
if [ -n "${DB_PASSWORD}" ]; then
    export PGPASSWORD="${DB_PASSWORD}"
fi
# Иначе недоступный порт заставит скрипт висеть неопределённо долго.
export PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-10}"

log "бэкап ${DB_NAME} с ${DB_HOST}:${DB_PORT} в ${TARGET}"

if ! "${PG_DUMP}" \
        --host="${DB_HOST}" \
        --port="${DB_PORT}" \
        --username="${DB_USER}" \
        --dbname="${DB_NAME}" \
        --format=custom \
        --compress=6 \
        --no-password \
        --file="${PARTIAL}" 2>"${PARTIAL}.err"; then
    if [ -s "${PARTIAL}.err" ]; then
        sed 's/^/    pg_dump: /' "${PARTIAL}.err" >&2 || true
    fi
    rm -f "${PARTIAL}.err"
    die "pg_dump не смог снять дамп ${DB_NAME} с ${DB_HOST}:${DB_PORT} (проверьте, что кластер поднят и доступы в ${ENV_FILE} верны)"
fi
rm -f "${PARTIAL}.err"

[ -s "${PARTIAL}" ] || die "pg_dump вернул 0, но файл дампа пуст: ${PARTIAL}"

DUMP_SIZE="$(wc -c <"${PARTIAL}" | tr -d ' ')"
# Пустой custom-дамп сам по себе весит порядка килобайта; меньше — файл заведомо обрезан.
if [ "${DUMP_SIZE}" -lt 512 ]; then
    die "дамп подозрительно мал (${DUMP_SIZE} байт), считаем его битым: ${PARTIAL}"
fi

# Главная проверка: архив должен открываться и содержать таблицы.
LISTING="${PARTIAL}.list"
if ! "${PG_RESTORE}" --list "${PARTIAL}" >"${LISTING}" 2>&1; then
    sed 's/^/    pg_restore: /' "${LISTING}" >&2 || true
    rm -f "${LISTING}"
    die "дамп не читается pg_restore --list, файл битый: ${PARTIAL}"
fi

TABLE_ENTRIES="$(grep -c ' TABLE ' "${LISTING}")" || TABLE_ENTRIES=0
rm -f "${LISTING}"
if [ "${TABLE_ENTRIES}" -lt 1 ]; then
    die "в дампе нет ни одной таблицы — похоже, снят не с той базы: ${PARTIAL}"
fi

mv "${PARTIAL}" "${TARGET}" || die "не удалось переименовать ${PARTIAL} в ${TARGET}"
chmod 600 "${TARGET}" 2>/dev/null || true
trap - EXIT

log "готово: ${TARGET} ($(du -h "${TARGET}" | cut -f1), таблиц в архиве: ${TABLE_ENTRIES})"

# Ротация. Имена вида <база>-YYYYmmdd-HHMMSS.dump сортируются лексикографически
# так же, как хронологически, поэтому достаточно обычного sort.
mapfile -t backups < <(find "${BACKUP_DIR}" -maxdepth 1 -type f -name "${DB_NAME}-*.dump" -printf '%f\n' | sort)
total="${#backups[@]}"
if [ "${total}" -gt "${BACKUP_KEEP}" ]; then
    to_delete=$((total - BACKUP_KEEP))
    for ((i = 0; i < to_delete; i++)); do
        rm -f -- "${BACKUP_DIR}/${backups[i]}" || die "не удалось удалить старый бэкап ${backups[i]}"
        log "ротация: удалён ${backups[i]}"
    done
    log "ротация: было ${total}, оставлено ${BACKUP_KEEP}"
else
    log "ротация: файлов ${total}, лимит ${BACKUP_KEEP} — удалять нечего"
fi

exit 0
