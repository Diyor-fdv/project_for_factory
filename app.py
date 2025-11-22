import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, date
from io import BytesIO
from pathlib import Path

DB_FILE = "belaz.db"

# Local logo file
LOGO_PATH = Path(__file__).parent / "logo.jpg"

# Admin parol (xohlasang o'zing o'zgartirasan)
ADMIN_CODE = "SJ8696"


# =====================================
#   SQLite соединение + создание таблиц
# =====================================

def get_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    return conn


def init_db():
    """Создаёт таблицы, если их нет. НИЧЕГО НЕ УДАЛЯЕТ."""
    conn = get_connection()
    cur = conn.cursor()

    # Asosiy jadval – hodkalar
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,          -- время
            day TEXT NOT NULL,         -- дата (YYYY-MM-DD)
            excavator TEXT NOT NULL,   -- экскаватор (1Y, 2Y, Y4, 18Y...)
            otval TEXT NOT NULL,       -- отвал (название)
            truck_id INTEGER NOT NULL, -- номер БелАЗа
            truck_class TEXT NOT NULL, -- тип: 130т / 220т / 240т / unknown
            base_volume REAL NOT NULL, -- базовый объём м³ (42/75/50)
            factor REAL NOT NULL,      -- коэффициент (1.0 или 0.5)
            volume REAL NOT NULL       -- фактический объём м³
        );
        """
    )

    # Otvallar jadvali – nomi + uzunligi
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS otvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            length REAL                -- длина (км или м), может быть NULL
        );
        """
    )

    conn.commit()
    conn.close()

    ensure_default_otvals()


def ensure_default_otvals():
    """
    Базовые отвалы – 4 старых + 2 новых МОФ-2, МОФ-3.
    Если нет – создаём.
    """
    default_otvals = [
        "Перегруз отвал",
        "2Ё ближний отвал",
        "2Ё дальний отвал",
        "А4 окисленный отвал",
        "МОФ-2",
        "МОФ-3",
    ]
    conn = get_connection()
    cur = conn.cursor()
    for name in default_otvals:
        cur.execute(
            "INSERT OR IGNORE INTO otvals (name, length) VALUES (?, NULL);",
            (name,)
        )
    conn.commit()
    conn.close()


# =========================
#   Бизнес-логика БелАЗов
# =========================

def get_volume_by_truck_id(truck_id: int):
    """
    Объём (м³) по номеру БелАЗа:
    0–99    → 42 м³   (130 т)
    100–140 → 75 м³   (220 т)
    200–205 → 50 м³   (240 т)
    """
    if 0 <= truck_id <= 99:
        return "130т", 42.0
    elif 100 <= truck_id <= 140:
        return "220т", 75.0
    elif 200 <= truck_id <= 205:
        return "240т", 50.0
    else:
        return "unknown", 0.0


# =========================
#   DB funksiyalar
# =========================

def insert_record(excavator: str, otval: str, truck_id: int, is_half: bool):
    conn = get_connection()
    cur = conn.cursor()

    truck_class, base_volume = get_volume_by_truck_id(truck_id)
    if base_volume == 0.0:
        conn.close()
        return None, "Объём для этого БелАЗа не определён (номер вне диапазона)."

    factor = 0.5 if is_half else 1.0
    volume = base_volume * factor

    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    day = now.strftime("%Y-%m-%d")

    cur.execute(
        """
        INSERT INTO records
        (ts, day, excavator, otval, truck_id, truck_class, base_volume, factor, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (ts, day, excavator, otval, truck_id, truck_class, base_volume, factor, volume)
    )

    conn.commit()
    conn.close()
    return volume, None


def get_daily_records(day_str: str, excavator: str) -> pd.DataFrame:
    """
    Все ходки за день по конкретному экскаватору (по всем отвалам этого экскаватора).
    """
    conn = get_connection()
    query = """
        SELECT id, ts, day, excavator, otval, truck_id, truck_class,
               base_volume, factor, volume
        FROM records
        WHERE day = ? AND excavator = ?
        ORDER BY ts;
    """
    df = pd.read_sql_query(query, conn, params=(day_str, excavator))
    conn.close()
    return df


def get_daily_aggregated_all(day_str: str) -> pd.DataFrame:
    """
    Агрегированный свод по всем экскаваторам за день:
    по (day, excavator, otval, truck_id) считаем trips и общий объём obem.
    """
    conn = get_connection()
    query = """
        SELECT
            day,
            excavator,
            otval,
            truck_id,
            COUNT(*) AS trips,
            SUM(volume) AS obem
        FROM records
        WHERE day = ?
        GROUP BY day, excavator, otval, truck_id
        ORDER BY excavator, otval, truck_id;
    """
    df = pd.read_sql_query(query, conn, params=(day_str,))
    conn.close()
    return df


def get_otval_summary(day_str: str) -> pd.DataFrame:
    """
    Свод по отвалам и экскаваторам:
    day, otval, excavator, total_obem, length
    """
    conn = get_connection()
    query = """
        SELECT
            r.day AS day,
            r.otval AS otval,
            r.excavator AS excavator,
            SUM(r.volume) AS obem,
            o.length AS length
        FROM records r
        LEFT JOIN otvals o ON r.otval = o.name
        WHERE r.day = ?
        GROUP BY r.day, r.otval, r.excavator, o.length
        ORDER BY r.otval, r.excavator;
    """
    df = pd.read_sql_query(query, conn, params=(day_str,))
    conn.close()
    return df


def get_otval_names() -> list[str]:
    """Otval nomlarini tartib bilan qaytaradi (id bo‘yicha)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name FROM otvals ORDER BY id;")
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_otvals_table() -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql_query("SELECT id, name, length FROM otvals ORDER BY id;", conn)
    conn.close()
    return df


def upsert_otval(name: str, length: float | None):
    conn = get_connection()
    cur = conn.cursor()
    # Agar bor bo'lsa length ni update, yo'q bo'lsa yangi qo'shamiz
    cur.execute(
        """
        INSERT INTO otvals (name, length)
        VALUES (?, ?)
        ON CONFLICT(name) DO UPDATE SET length = excluded.length;
        """,
        (name, length)
    )
    conn.commit()
    conn.close()


# =====================================
#   Streamlit UI
# =====================================

EXCAVATORS = [
    "1Y", "2Y", "Y4",
    "13Y",
    "18Y", "19Y", "20Y", "21Y", "22Y", "23Y", "24Y", "25Y", "26Y", "27Y",
    "28Y", "29Y", "30Y", "31Y", "32Y"
]


def init_session_state():
    if "selected_excavator" not in st.session_state:
        st.session_state["selected_excavator"] = None
    if "selected_otval" not in st.session_state:
        st.session_state["selected_otval"] = None
    if "is_admin" not in st.session_state:
        st.session_state["is_admin"] = False


def main():
    st.set_page_config(page_title='Карьер "БАРАКАЛИ"- @SJ8696', layout="wide")
    init_db()
    init_session_state()

    # ---------- HEADER ----------
    header_col1, header_col2 = st.columns([1, 5])
    with header_col1:
        if LOGO_PATH.exists():
            st.image(str(LOGO_PATH), width=140)
        else:
            st.write("⛏️")
    with header_col2:
        st.markdown(
            '<h2 style="margin-bottom:0;">Карьер "БАРАКАЛИ"- @SJ8696</h2>'
            '<h4 style="margin-top:0;">Учёт ходок БелАЗов по экскаваторам</h4>',
            unsafe_allow_html=True,
        )

    st.divider()

    # Admin switch
    admin_col1, admin_col2 = st.columns([2, 3])
    with admin_col1:
        st.caption("Режим администратора (для мастера / начальства)")
        admin_input = st.text_input("Admin code", type="password", label_visibility="collapsed")
    with admin_col2:
        if st.button("🔐 Войти как админ"):
            if admin_input == ADMIN_CODE:
                st.session_state["is_admin"] = True
                st.success("Админ режим активирован.")
            else:
                st.error("Неверный admin code.")
        if st.button("🚪 Выйти из админ режима"):
            st.session_state["is_admin"] = False

    is_admin = st.session_state["is_admin"]

    st.divider()

    selected_excavator = st.session_state["selected_excavator"]
    selected_otval = st.session_state["selected_otval"]

    # ================= STEP 1: ВЫБОР ЭКСКАВАТОРА =================
    if selected_excavator is None:
        st.subheader("Выберите экскаватор")

        # 3 ta ustun – telefonda ham, laptopda ham normalroq ko'rinadi
        cols = st.columns(3)
        for i, exc in enumerate(EXCAVATORS):
            col = cols[i % 3]
            if col.button(exc, use_container_width=True):
                st.session_state["selected_excavator"] = exc
                st.session_state["selected_otval"] = None
                st.rerun()
        return  # экскаватор танланмагунча пастга тушмаймиз

    # Кнопка «Сменить экскаватор»
    st.markdown(f"### Экскаватор: **{selected_excavator}**")
    if st.button("⏪ Сменить экскаватор"):
        st.session_state["selected_excavator"] = None
        st.session_state["selected_otval"] = None
        st.rerun()

    st.divider()

    # ================= STEP 2: ВЫБОР ОТВАЛА =================
    otval_names = get_otval_names()

    if selected_otval is None:
        st.subheader("Выберите отвал")

        cols = st.columns(2)
        for i, otv in enumerate(otval_names):
            col = cols[i % 2]
            if col.button(otv, use_container_width=True):
                st.session_state["selected_otval"] = otv
                st.rerun()
        return

    # Кнопка «Сменить отвал»
    st.markdown(f"**Отвал:** {selected_otval}")
    change_otval_col1, change_otval_col2 = st.columns(2)
    with change_otval_col1:
        if st.button("⏪ Сменить отвал"):
            st.session_state["selected_otval"] = None
            st.rerun()

    st.divider()

    # ================= STEP 3: ФОРМА ВВОДА + ОТЧЁТ =================

    tab1, tab2 = st.tabs(["📝 Ввод ходки (для машиниста)", "📊 Общий свод / Admin"])

    # ---------- TAB 1: ВВОД + СВОЙ СПИСОК ----------
    with tab1:
        st.subheader(f"Новая ходка — {selected_excavator}, {selected_otval}")

        with st.form("hodka_form", clear_on_submit=True):
            col1, col2 = st.columns(2)

            with col1:
                belaz_input = st.text_input(
                    "Номер БелАЗа",
                    value="",
                    placeholder="Например: 201"
                )

            with col2:
                is_half = st.checkbox("Полупустая (0.5 загрузки)")

            submitted = st.form_submit_button("💾 Сохранить ходку")

        if submitted:
            belaz_str = belaz_input.strip()

            if not belaz_str:
                st.error("Введите номер БелАЗа.")
            elif not belaz_str.isdigit():
                st.error("Номер БелАЗа должен быть числом.")
            else:
                truck_id = int(belaz_str)
                volume, error = insert_record(selected_excavator, selected_otval, truck_id, is_half)

                if error:
                    st.error("❌ " + error)
                else:
                    st.success(
                        f"Ходка сохранена: экскаватор {selected_excavator} | отвал: {selected_otval} | "
                        f"БелАЗ №{truck_id} | "
                        f"{'0.5 загрузки' if is_half else 'полная загрузка'} | "
                        f"{volume:.2f} м³"
                    )

        # Mashinist uchun – bugungi kun bo‘yicha o‘z ekskavatorining ro‘yxati
        today_str = date.today().strftime("%Y-%m-%d")
        st.markdown(f"### Сегодняшние ходки ({today_str}) по экскаватору {selected_excavator}")

        df_ex_today = get_daily_records(today_str, selected_excavator)

        if df_ex_today.empty:
            st.info("Сегодня пока нет сохранённых ходок для этого экскаватора.")
        else:
            df_ex_today = df_ex_today.copy()
            df_ex_today["xodka"] = range(1, len(df_ex_today) + 1)
            df_ex_view = df_ex_today.rename(columns={
                "truck_id": "belaz_no",
                "volume": "obem"
            })
            df_ex_view = df_ex_view[
                ["day", "ts", "excavator", "otval", "belaz_no",
                 "truck_class", "base_volume", "factor", "obem", "xodka"]
            ]
            st.dataframe(df_ex_view, use_container_width=True)

    # ---------- TAB 2: ОБЩИЙ СВОД + ADMIN PANEL ----------
    with tab2:
        st.subheader("Общий свод по всем экскаваторам")

        today = date.today()
        selected_day = st.date_input("Дата свода", value=today, key="master_date")
        day_str = selected_day.strftime("%Y-%m-%d")

        st.markdown(f"### Дата: **{day_str}**")

        df_all = get_daily_aggregated_all(day_str)

        if df_all.empty:
            st.info("Нет данных за выбранную дату по всем экскаваторам.")
        else:
            df_all = df_all.copy()
            df_all = df_all.rename(columns={
                "truck_id": "belaz_no"
            })

            total_trips_all = df_all["trips"].sum()
            total_obem_all = df_all["obem"].sum()

            st.markdown("#### Агрегированный свод (день / экскаватор / отвал / БелАЗ)")
            st.dataframe(df_all, use_container_width=True)

            col_a, col_b = st.columns(2)
            with col_a:
                st.metric("Общее количество ходок (все экскаваторы)", int(total_trips_all))
            with col_b:
                st.metric("Общий объём (м³) по всем экскаваторам", f"{total_obem_all:.2f}")

        # --- ADMIN PANEL ---
        st.divider()
        st.markdown("### 🔐 Admin panel")

        if not is_admin:
            st.info("Для доступа к admin panel введите верный admin code сверху.")
        else:
            st.success("Админ режим активен.")

            # 1) Свод по отвалам и экскаваторам
            st.markdown("#### Свод по отвалам (отвал + экскаватор, общий объём)")

            df_otval = get_otval_summary(day_str)

            if df_otval.empty:
                st.info("Нет данных по отвалам за выбранную дату.")
            else:
                st.dataframe(df_otval, use_container_width=True)

            # 2) Excel экспорт – ОДИН SHEET:
            #    - детальные агрегаты по БелАЗам
            #    - плюс строки с суммой по (отвал, экскаватор)

            if not df_all.empty:
                st.markdown("#### 📥 Экспорт общего отчёта (1 лист, все данные)")

                # DETAIL qismi
                detail_df = df_all.copy()
                detail_df["row_type"] = "DETAIL"

                # OTVAL_SUM qismi
                if not df_otval.empty:
                    otval_sum_df = df_otval.copy()
                    otval_sum_df["row_type"] = "OTVAL_SUM"
                    otval_sum_df["belaz_no"] = ""
                    otval_sum_df["trips"] = ""
                    # detail_df bilan ustunlarni tenglashtirish
                    otval_sum_df = otval_sum_df.rename(columns={"length": "otval_length"})
                    detail_df["otval_length"] = None

                    # bir xil ustunlar ro'yxati
                    cols = [
                        "row_type",
                        "day",
                        "excavator",
                        "otval",
                        "belaz_no",
                        "trips",
                        "obem",
                        "otval_length",
                    ]

                    detail_export = detail_df[["row_type", "day", "excavator", "otval",
                                               "belaz_no", "trips", "obem", "otval_length"]]

                    # otval_sum_df da yetishmaydigan ustunlarni qo'shamiz
                    if "obem" not in otval_sum_df.columns:
                        # bu hol bo'lmaydi, lekin xavfsizlik uchun
                        otval_sum_df["obem"] = otval_sum_df.get("obem", 0)

                    otval_export = otval_sum_df[["row_type", "day", "excavator", "otval",
                                                 "belaz_no", "trips", "obem", "otval_length"]]

                    # GENERAL TOTAL qator
                    total_row = {
                        "row_type": "GRAND_TOTAL",
                        "day": "",
                        "excavator": "",
                        "otval": "",
                        "belaz_no": "",
                        "trips": total_trips_all,
                        "obem": total_obem_all,
                        "otval_length": "",
                    }

                    export_df = pd.concat(
                        [detail_export, otval_export, pd.DataFrame([total_row])],
                        ignore_index=True
                    )
                else:
                    # faqat detail, otval_summary bo'sh
                    detail_df = df_all.copy()
                    detail_df["row_type"] = "DETAIL"
                    detail_df["otval_length"] = None

                    total_row = {
                        "row_type": "GRAND_TOTAL",
                        "day": "",
                        "excavator": "",
                        "otval": "",
                        "belaz_no": "",
                        "trips": total_trips_all,
                        "obem": total_obem_all,
                        "otval_length": "",
                    }

                    export_df = pd.concat(
                        [detail_df, pd.DataFrame([total_row])],
                        ignore_index=True
                    )

                output = BytesIO()
                with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                    export_df.to_excel(writer, index=False, sheet_name="Данные")

                st.download_button(
                    label="⬇️ Скачать общий Excel-файл (admin)",
                    data=output.getvalue(),
                    file_name=f"belaz_all_{day_str}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

            st.divider()

            # 3) Управление отвалами (добавить / изменить длину)
            st.markdown("#### Управление отвалами")

            df_otvals_table = get_otvals_table()
            st.dataframe(df_otvals_table, use_container_width=True)

            st.markdown("**Добавить/обновить отвал**")
            with st.form("otval_form"):
                col1, col2 = st.columns(2)
                with col1:
                    new_otval_name = st.text_input(
                        "Название отвала",
                        placeholder="Например: МОФ-4 или 2Ё ближний отвал",
                    )
                with col2:
                    length_input = st.text_input(
                        "Длина (км или м, можно пусто)",
                        placeholder="Например: 2.5"
                    )

                save_otval = st.form_submit_button("💾 Сохранить отвал")

            if save_otval:
                name = new_otval_name.strip()
                if not name:
                    st.error("Название отвала обязательно.")
                else:
                    if length_input.strip() == "":
                        length_val = None
                    else:
                        try:
                            length_val = float(length_input.replace(",", "."))
                        except ValueError:
                            st.error("Длина должна быть числом (например 2.5).")
                            length_val = None

                    if length_input.strip() == "" or length_val is not None:
                        upsert_otval(name, length_val)
                        st.success("Отвал сохранён/обновлён.")
                        st.rerun()


if __name__ == "__main__":
    main()
