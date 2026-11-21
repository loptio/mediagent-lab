"""驗收例子用的中文值 ↔ 代碼對照（《資料模型》§2）。

步驟裡的中文值一律先轉成代碼再比對；表格裡直接寫代碼的（例如 DRAFT）原樣通過。
"""

from datetime import UTC, datetime, timedelta, timezone

TAIPEI = timezone(timedelta(hours=8))

ROLE = {"管理員": "admin", "發佈者": "publisher", "撰稿者": "writer"}
USER_STATUS = {"啟用": "active", "停用": "disabled"}
ACTOR_TYPE = {"使用者": "user", "系統": "system"}
PLATFORM = {"Threads": "threads", "Instagram": "instagram", "Discord": "discord"}
AUTH_STATUS = {"有效": "valid", "失效": "invalid"}
POST_STATUS = {
    "草稿": "DRAFT",
    "已排程": "SCHEDULED",
    "發佈中": "PUBLISHING",
    "發佈完成": "PUBLISHED",
    "部分失敗": "PARTIALLY_FAILED",
    "全部失敗": "FAILED",
}
RECORD_STATUS = {"待發佈": "PENDING", "成功": "SUCCEEDED", "失敗": "FAILED", "已取消": "CANCELLED"}
FAILURE_REASON = {
    "帳號授權過期": "AUTH_EXPIRED",
    "帳號授權失效": "AUTH_INVALID",
    "平台暫時無法連線": "PLATFORM_UNAVAILABLE",
    "內容不符合平台限制": "CONTENT_REJECTED",
    "發佈逾時": "TIMEOUT",
    "其他": "OTHER",
}
HISTORY_REASON = {
    "設定排程": "SCHEDULE_SET",
    "立即發佈": "PUBLISH_NOW",
    "新增目標平台帳號": "TARGET_ADDED",
    "修改目標平台帳號": "TARGET_MODIFIED",
    "目標平台帳號已移除": "TARGET_ACCOUNT_REMOVED",
    "取消排程": "SCHEDULE_CANCELLED",
    "重新排程": "RESCHEDULED",
    "刪除貼文": "POST_DELETED",
    "發佈貼文：成功": "PUBLISH_SUCCEEDED",
    "發佈貼文：失敗": "PUBLISH_FAILED",
    "重試發佈：開始": "RETRY_STARTED",
    "重試發佈：成功": "RETRY_SUCCEEDED",
    "重試發佈：失敗": "RETRY_FAILED",
    "發佈逾時恢復：已確認發佈": "RECOVERY_CONFIRMED_PUBLISHED",
    "發佈逾時恢復：確認未發佈": "RECOVERY_CONFIRMED_NOT_PUBLISHED",
    "發佈逾時恢復：無法確認": "RECOVERY_UNCONFIRMED",
    "自動重試發佈：成功": "AUTO_RETRY_SUCCEEDED",
    "自動重試發佈：失敗": "AUTO_RETRY_FAILED",
}
AUDIT_ACTION = {
    "登入": "LOGIN",
    "登出": "LOGOUT",
    "登出所有裝置": "LOGOUT_ALL",
    "建立幹部帳號": "USER_CREATE",
    "調整角色": "USER_ROLE_CHANGE",
    "停用帳號": "USER_DISABLE",
    "啟用帳號": "USER_ENABLE",
    "解除鎖定": "USER_UNLOCK",
    "連結平台帳號": "PLATFORM_LINK",
    "重新連結平台帳號": "PLATFORM_RELINK",
    "移除平台帳號": "PLATFORM_REMOVE",
    "發佈貼文": "POST_PUBLISH",
    "設定排程": "POST_SCHEDULE",
    "取消排程": "SCHEDULE_CANCEL",
    "重試發佈": "PUBLISH_RETRY",
    "自動重試發佈": "PUBLISH_AUTO_RETRY",
    "複製為新草稿": "POST_COPY",
    # 稽核查詢的操作類型也可以是另外兩種事件
    "登入失敗": "LOGIN_FAILED",
    "連結平台帳號失敗": "LINK_FAILED",
    "重新連結平台帳號失敗": "RELINK_FAILED",
}
AUDIT_REASON = {"平台確認未發佈": "PLATFORM_CONFIRMED_NOT_PUBLISHED"}
TARGET_TYPE = {"使用者帳號": "user_account", "平台帳號": "platform_account", "貼文": "post"}
TARGET_RESULT = {"成功": "SUCCEEDED", "失敗": "FAILED", "未重試": "NOT_RETRIED"}
SKIP_REASON = {
    "先前已成功": "ALREADY_SUCCEEDED",
    "授權失效而跳過": "AUTH_INVALID_SKIPPED",
    "已移除而跳過": "REMOVED_SKIPPED",
}
EVENT_TYPE = {
    "登入失敗": "LOGIN_FAILED",
    "連結平台帳號失敗": "LINK_FAILED",
    "重新連結平台帳號失敗": "RELINK_FAILED",
}
LOGIN_FAILURE = {
    "密碼錯誤": "WRONG_PASSWORD",
    "帳號停用": "ACCOUNT_DISABLED",
    "帳號鎖定": "ACCOUNT_LOCKED",
    "帳號不存在": "ACCOUNT_NOT_FOUND",
}
AUTH_FAILURE = {
    "平台授權失敗": "PLATFORM_AUTH_FAILED",
    "Webhook 驗證無效": "WEBHOOK_INVALID",
    "暫時無法驗證": "VERIFICATION_UNAVAILABLE",
    "平台帳號識別碼不一致": "PLATFORM_ID_MISMATCH",
}
RECORD_KIND = {"稽核紀錄": "audit", "登入安全事件": "login_security", "平台授權事件": "platform_auth"}
YES_NO = {"是": True, "否": False, "true": True, "false": False}


def code(mapping: dict[str, str], value: str) -> str | None:
    """中文值轉代碼；空字串為 None；已經是代碼的原樣回傳。"""
    value = value.strip()
    if value == "":
        return None
    return mapping.get(value, value)


def tw_time(value: str) -> datetime | None:
    """表格與步驟裡的時間一律是台灣時間（「2026-10-05 10:00」等），轉成 UTC。"""
    value = value.strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=TAIPEI).astimezone(UTC)
        except ValueError:
            continue
    raise ValueError(f"無法解析的時間：{value!r}")
