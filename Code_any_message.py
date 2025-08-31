import time
import re
import sys
import json
import logging
from logging.handlers import RotatingFileHandler
from typing import Optional, Dict, Any, List, Tuple
import requests
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit
from datetime import datetime

# =====================[ НАСТРОЙКИ ]=====================
TOKEN: str = "токен"   # твой токен
ACTIVATION_ID: str = "55952540009"                 # id активации

REORDER_REGEX: Optional[str] = r"(?<!\d)\d{6}(?!\d)"
REORDER_SUBJECT: Optional[str] = None

REORDER_EMAIL: Optional[str] = None
REORDER_SITE: Optional[str] = None

SITE_NAME: str = "tiktok"      
USE_CUSTOM_REGEX: bool = False
CUSTOM_REGEX: Optional[str] = None  
REQUEST_PREVIEW_HTML: bool = True

# Ожидание
TIMEOUT_SEC: int = 180
POLL_INTERVAL_SEC: int = 3

# Сетевые опции
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AnyMessageClient/1.2"
}
PROXIES: Optional[Dict[str, str]] = None
VERIFY_SSL: bool = True

# Логирование
LOG_LEVEL = logging.INFO      
LOG_FILE = "anymessage.log"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3

# Сохранение ответов
SAVE_RESPONSE_JSON_PATH = "last_anymessage_response.json"  # сырой последний ответ API
SAVE_RESULT_JSON_PATH = "last_anymessage_result.json"      # итог (код/тело/последний payload)
SAVE_EVERY_RESPONSE_WITH_TS = False                       
# =======================================================

BASE_URL = "https://api.anymessage.shop"

# Паттерны из твоего скрипта
DEFAULT_REGEX_PATTERNS: Dict[str, str] = {
    "tiktok": r"\b(\d{6})\b",     # 6-значный
    "instagram": r"\b(\d{6})\b",  # 6-значный
    "default": r"\b(\d{4,8})\b"   # 4..8 цифр
}


# ---------- ЛОГГЕР ----------
logger = logging.getLogger("anymessage")
logger.setLevel(LOG_LEVEL)
_fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                         datefmt="%Y-%m-%d %H:%M:%S")
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(_fmt)
ch.setLevel(LOG_LEVEL)
fh = RotatingFileHandler(LOG_FILE, maxBytes=LOG_MAX_BYTES,
                         backupCount=LOG_BACKUP_COUNT, encoding="utf-8")
fh.setFormatter(_fmt)
fh.setLevel(LOG_LEVEL)
if not logger.handlers:
    logger.addHandler(ch)
    logger.addHandler(fh)


class AnyMessageError(Exception):
    pass


def _redact_token_in_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        q = dict(parse_qsl(parts.query, keep_blank_values=True))
        if "token" in q and q["token"]:
            q["token"] = q["token"][:3] + "***" + q["token"][-3:]
        new_query = urlencode(q, doseq=True)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))
    except Exception:
        return url


def _save_json(obj: Dict[str, Any], path: str) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        logger.info(f"JSON сохранён: {path}")
    except Exception as e:
        logger.warning(f"Не удалось сохранить JSON в {path}: {e}")


def _maybe_save_every_response(obj: Dict[str, Any]) -> None:
    if not SAVE_EVERY_RESPONSE_WITH_TS:
        return
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = f"responses/{ts}.json"
        import os
        os.makedirs("responses", exist_ok=True)
        _save_json(obj, path)
    except Exception as e:
        logger.debug(f"Не удалось сохранить по времени: {e}")


def _normalize_wait_message(text: str) -> Optional[Dict[str, Any]]:
    low = text.strip().lower()
    if ("wait message" in low
        or "письмо ещё не пришло" in low
        or "письмо еще не пришло" in low):
        return {"status": "error", "value": "wait message", "raw": text}
    return None


def _parse_json_loose(text: str) -> Optional[Dict[str, Any]]:
    m = re.search(r'(\{.*\})', text, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def _get(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        req = requests.Request("GET", url, params=params, headers=HEADERS)
        prep = req.prepare()
        safe_url = _redact_token_in_url(prep.url or url)
        logger.debug(f"GET {safe_url}")
    except Exception:
        safe_url = url

    try:
        r = requests.get(url, params=params, timeout=30,
                         headers=HEADERS, proxies=PROXIES, verify=VERIFY_SSL)
    except requests.exceptions.RequestException as e:
        logger.error(f"HTTP connect error: {e}")
        raise AnyMessageError(f"HTTP connect error: {e}") from e

    content_type = r.headers.get("Content-Type", "")
    body_text = r.text or ""
    logger.debug(f"-> {r.status_code} Content-Type={content_type}; len={len(body_text)}")

    if r.status_code >= 400:
        snippet = body_text[:200].replace("\n", "\\n")
        logger.error(f"HTTP {r.status_code} from {_redact_token_in_url(r.url)}; body[:200]={snippet!r}")
        raise AnyMessageError(f"HTTP {r.status_code}")

    # пробуем обычный JSON
    try:
        data = r.json()
        _save_json(data, SAVE_RESPONSE_JSON_PATH)
        _maybe_save_every_response(data)
        return data
    except requests.exceptions.JSONDecodeError:
        # текст/HTML → нормализуем
        nm = _normalize_wait_message(body_text)
        if nm:
            _save_json(nm, SAVE_RESPONSE_JSON_PATH)
            _maybe_save_every_response(nm)
            return nm

        maybe = _parse_json_loose(body_text)
        if maybe is not None:
            _save_json(maybe, SAVE_RESPONSE_JSON_PATH)
            _maybe_save_every_response(maybe)
            return maybe

        pseudo = {
            "status": "success",    
            "value": None,
            "message": body_text,    
            "non_json": True,
            "content_type": content_type,
        }
        logger.info("Получен не-JSON ответ; передаём как pseudo-JSON с полем 'message'.")
        _save_json(pseudo, SAVE_RESPONSE_JSON_PATH)
        _maybe_save_every_response(pseudo)
        return pseudo


def reorder_activation(
    token: str,
    activation_id: Optional[str] = None,
    *,
    email: Optional[str] = None,
    site: Optional[str] = None,
    regex: Optional[str] = None,
    subject: Optional[str] = None,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"token": token}
    url = f"{BASE_URL}/email/reorder"

    if activation_id:
        params["id"] = activation_id
    else:
        if not (email and site):
            raise ValueError("Нужен activation_id ИЛИ (email + site) для reorder")
        params["email"] = email
        params["site"] = site

    if regex:
        params["regex"] = regex
    if subject:
        params["subject"] = subject

    data = _get(url, params)
    if data.get("status") != "success":
        logger.error(f"Reorder error payload: {data}")
        raise AnyMessageError(f"Reorder error: {data}")
    logger.info(f"Reorder OK (id/email): {data.get('id')}/{data.get('email')}")
    return data


def get_message_once(
    token: str,
    activation_id: str,
    *,
    preview_html: bool = False,
) -> Dict[str, Any]:
    url = f"{BASE_URL}/email/getmessage"
    params = {"token": token, "id": activation_id}
    if preview_html:
        params["preview"] = 1
    return _get(url, params)

def extract_code_from_message(
    site_name: str,
    html_or_text: str,
    plain_value: str,
    use_custom_regex: bool,
    custom_regex: Optional[str],
    logger_prefix: str = "extract"
) -> Optional[str]:
    """
    Возвращает код по той же логике, что у тебя:
      1) готовое value: циферки длиной 4..8 → код
      2) кастомный regex, если включен
      3) паттерн для конкретного сайта
      4) все дефолт-паттерны
    """
    text_to_search = (html_or_text or "") + " " + (plain_value or "")
    plain = (plain_value or "").strip()

    # 1) plain_value как готовый код
    if plain and plain.isdigit() and 4 <= len(plain) <= 8:
        logger.info(f"[{logger_prefix}] plain_value выглядит как код: {plain}")
        return plain

    # 2) кастомный regex
    if use_custom_regex and custom_regex:
        try:
            matches = re.findall(custom_regex, text_to_search, re.IGNORECASE)
            if matches:
                code = matches[0] if isinstance(matches[0], str) else matches[0][0]
                code = str(code).strip()
                if code.isdigit() and 4 <= len(code) <= 8:
                    logger.info(f"[{logger_prefix}] код найден кастомным regex: {code}")
                    return code
        except Exception as e:
            logger.warning(f"[{logger_prefix}] ошибка кастомного regex: {e}")

    # 3) паттерн для сайта
    site_key = (site_name or "default").lower()
    site_pattern = DEFAULT_REGEX_PATTERNS.get(site_key, DEFAULT_REGEX_PATTERNS["default"])
    try:
        matches = re.findall(site_pattern, text_to_search)
        if matches:
            code = matches[0] if isinstance(matches[0], str) else matches[0][0]
            code = str(code).strip()
            if code.isdigit() and 4 <= len(code) <= 8:
                logger.info(f"[{logger_prefix}] код найден паттерном сайта '{site_key}': {code}")
                return code
    except Exception as e:
        logger.warning(f"[{logger_prefix}] ошибка паттерна сайта '{site_key}': {e}")

    # 4) все дефолт-паттерны
    for name, pattern in DEFAULT_REGEX_PATTERNS.items():
        try:
            matches = re.findall(pattern, text_to_search)
            if matches:
                code = matches[0] if isinstance(matches[0], str) else matches[0][0]
                code = str(code).strip()
                if code.isdigit() and 4 <= len(code) <= 8:
                    logger.info(f"[{logger_prefix}] код найден паттерном '{name}': {code}")
                    return code
        except Exception as e:
            logger.warning(f"[{logger_prefix}] ошибка паттерна '{name}': {e}")

    return None


def wait_for_code(
    token: str,
    activation_id: str,
    *,
    timeout_sec: int,
    poll_interval_sec: int,
    site_name: str,
    use_custom_regex: bool,
    custom_regex: Optional[str],
    do_preview_html: bool,
) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    tries = 0
    last_payload: Optional[Dict[str, Any]] = None

    while time.monotonic() < deadline:
        tries += 1
        data = get_message_once(
            token=token,
            activation_id=activation_id,
            preview_html=do_preview_html
        )
        last_payload = data
        status = data.get("status")
        plain_value = str(data.get("value") or "").strip()
        message_text = data.get("message") or ""

        logger.debug(
            f"poll #{tries} status={status!r} plain_value={plain_value!r} "
            f"msg_len={len(message_text)}"
        )

        if status == "error":
            if data.get("value") == "wait message":
                time.sleep(poll_interval_sec)
                continue
            raise AnyMessageError(f"API error: {data}")

        if status == "success":
            # 1) пробуем твою логику извлечения кода
            code = extract_code_from_message(
                site_name=site_name,
                html_or_text=message_text,
                plain_value=plain_value,
                use_custom_regex=use_custom_regex,
                custom_regex=custom_regex,
                logger_prefix=f"poll#{tries}"
            )
            if code:
                result = {
                    "code": code,
                    "raw_value": plain_value or None,
                    "message": message_text,
                    "api_payload": data,
                }
                _save_json(result, SAVE_RESULT_JSON_PATH)
                return result

            # 2) если не нашли — ждём ещё
            time.sleep(poll_interval_sec)
            continue

        logger.warning(f"Unexpected payload on poll #{tries}: {data}")
        time.sleep(poll_interval_sec)

    fail_obj = {
        "error": f"Timeout {timeout_sec}s while waiting for code",
        "last_payload": last_payload,
    }
    _save_json(fail_obj, SAVE_RESULT_JSON_PATH)
    raise AnyMessageError(fail_obj["error"])


def balance_check(token: str) -> Optional[Dict[str, Any]]:
    try:
        data = _get(f"{BASE_URL}/user/balance", {"token": token})
        if data.get("status") == "success":
            logger.info(f"Баланс: {data.get('balance')}")
        else:
            logger.warning(f"Balance check non-success: {data}")
        return data
    except AnyMessageError as e:
        logger.warning(f"Balance check failed: {e}")
        return None


def main():

    if not TOKEN or TOKEN.startswith("YOUR_"):
        logger.error("Заполни TOKEN вверху файла.")
        sys.exit(2)
    if not ACTIVATION_ID or ACTIVATION_ID == "1234567890":
        logger.error("Заполни ACTIVATION_ID вверху файла.")
        sys.exit(2)

    if REORDER_REGEX or REORDER_SUBJECT or (REORDER_EMAIL and REORDER_SITE):
        try:
            reorder_activation(
                token=TOKEN,
                activation_id=None if (REORDER_EMAIL and REORDER_SITE) else ACTIVATION_ID,
                email=REORDER_EMAIL,
                site=REORDER_SITE,
                regex=REORDER_REGEX,
                subject=REORDER_SUBJECT,
            )
        except AnyMessageError as e:
            logger.exception(f"Reorder error: {e}")
            sys.exit(3)

    try:
        res = wait_for_code(
            token=TOKEN,
            activation_id=ACTIVATION_ID,
            timeout_sec=TIMEOUT_SEC,
            poll_interval_sec=POLL_INTERVAL_SEC,
            site_name=SITE_NAME,
            use_custom_regex=USE_CUSTOM_REGEX,
            custom_regex=CUSTOM_REGEX,
            do_preview_html=REQUEST_PREVIEW_HTML,  
        )
    except AnyMessageError as e:
        logger.exception(f"Ошибка ожидания кода: {e}")
        sys.exit(1)

    
    print(res["code"] if res["code"] is not None else "")


if __name__ == "__main__":
    main()
