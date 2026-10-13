"""Safe configuration for the three customizable quick actions in the Water POS-inspired theme."""

WATER_PROJECT_ACTIONS = {
    "clients": {
        "label": "العملاء",
        "icon": "bi-people-fill",
        "endpoint": "master_data.clients",
        "permission": "clients.view",
    },
    "vouchers": {
        "label": "سند جديد",
        "icon": "bi-receipt",
        "endpoint": "operations.vouchers",
        "permission": "vouchers.view",
    },
    "collector": {
        "label": "التحصيل",
        "icon": "bi-upc-scan",
        "endpoint": "collector.index",
        "permission": "collector.post",
    },
    "reports": {
        "label": "التقارير",
        "icon": "bi-bar-chart-line",
        "endpoint": "reports.index",
        "permission": "reports.view",
    },
    "employees": {
        "label": "الموظفون",
        "icon": "bi-person-workspace",
        "endpoint": "master_data.employees",
        "permission": "employees.view",
    },
    "agents": {
        "label": "الوكلاء",
        "icon": "bi-person-badge",
        "endpoint": "master_data.agents",
        "permission": "agents.view",
    },
    "vehicles": {
        "label": "المركبات",
        "icon": "bi-truck-front",
        "endpoint": "master_data.vehicles",
        "permission": "vehicles.view",
    },
    "accounts": {
        "label": "الحسابات",
        "icon": "bi-diagram-3",
        "endpoint": "accounting.accounts",
        "permission": "accounting.view",
    },
    "payroll": {
        "label": "الرواتب",
        "icon": "bi-wallet2",
        "endpoint": "operations.payroll",
        "permission": "payroll.view",
    },
    "expenses": {
        "label": "المصروفات",
        "icon": "bi-cash-stack",
        "endpoint": "operations.expenses",
        "permission": "expenses.view",
    },
}

DEFAULT_WATER_PROJECT_SHORTCUTS = (
    {"slot": 1, "action": "clients"},
    {"slot": 2, "action": "vouchers"},
    {"slot": 3, "action": "reports"},
)

WATER_PROJECT_ICON_OPTIONS = (
    {"value": "bi-people-fill", "label": "مجموعة أشخاص"},
    {"value": "bi-person-plus", "label": "إضافة شخص"},
    {"value": "bi-person-workspace", "label": "الموظفون"},
    {"value": "bi-person-badge", "label": "بطاقة شخص"},
    {"value": "bi-receipt", "label": "سند"},
    {"value": "bi-receipt-cutoff", "label": "سند مع تفاصيل"},
    {"value": "bi-upc-scan", "label": "تحصيل ومسح"},
    {"value": "bi-bar-chart-line", "label": "تقارير"},
    {"value": "bi-truck-front", "label": "مركبة"},
    {"value": "bi-diagram-3", "label": "شجرة حسابات"},
    {"value": "bi-wallet2", "label": "محفظة ورواتب"},
    {"value": "bi-cash-stack", "label": "نقد ومصروفات"},
    {"value": "bi-cash-coin", "label": "مبلغ نقدي"},
    {"value": "bi-clipboard-check", "label": "إجراء ومراجعة"},
    {"value": "bi-calendar2-check", "label": "تقويم"},
    {"value": "bi-journal-text", "label": "دفتر وسجلات"},
    {"value": "bi-gear", "label": "إعدادات"},
    {"value": "bi-plus-lg", "label": "علامة إضافة"},
)

WATER_PROJECT_ICON_VALUES = frozenset(item["value"] for item in WATER_PROJECT_ICON_OPTIONS)


def shortcut_setting_key(slot, field):
    """Return the setting key for an action slot and one of its fields."""
    if slot not in (1, 2, 3) or field not in {"action", "label", "icon"}:
        raise ValueError("إعداد زر غير صالح")
    return f"water_project_shortcut_{slot}_{field}"


def configured_water_project_shortcuts(read_setting, permission_check=None, url_builder=None):
    """Read saved actions, enforce the icon/action allowlists, and optionally build safe links."""
    shortcuts = []
    for default in DEFAULT_WATER_PROJECT_SHORTCUTS:
        slot = default["slot"]
        action_key = read_setting(shortcut_setting_key(slot, "action"), default["action"])
        if action_key not in WATER_PROJECT_ACTIONS:
            action_key = default["action"]
        action = WATER_PROJECT_ACTIONS[action_key]
        if permission_check is not None and not permission_check(action["permission"]):
            continue

        raw_label = read_setting(shortcut_setting_key(slot, "label"), action["label"])
        label = str(raw_label or "").strip()[:28] or action["label"]
        icon = read_setting(shortcut_setting_key(slot, "icon"), action["icon"])
        if icon not in WATER_PROJECT_ICON_VALUES:
            icon = action["icon"]

        item = {
            "slot": slot,
            "action": action_key,
            "label": label,
            "icon": icon,
            "endpoint": action["endpoint"],
            "permission": action["permission"],
        }
        if url_builder is not None:
            item["url"] = url_builder(action["endpoint"])
        shortcuts.append(item)
    return shortcuts
