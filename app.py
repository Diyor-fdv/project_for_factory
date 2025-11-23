import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, date, timedelta
from io import BytesIO

DB_FILE = "belaz.db"
LOGO_URL = "https://agmk.uz/uploads/news/3a1b485c044e3d563acdd095d26ee287.jpg"
ADMIN_CODE = "shjsh707"

# maxsus belgi – Ж/Р rejimi
OTVAL_JR = "__J_R__"


# =======================
#  Vaqt (Toshkent UTC+5)
# =======================

def get_now_tashkent():
    """Server UTC bo'lsa ham, bu yerda +5 soat qo'shib Toshkent vaqti qilamiz."""
    return datetime.utcnow() + timedelta(hours=5)


# =======================
#  SQLite + jadvallar
# =======================

def get_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    # Hodkalar (BelAZ)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            day TEXT NOT NULL,
            excavator TEXT NOT NULL,
            otval TEXT NOT NULL,
            truck_id INTEGER NOT NULL,
            truck_class TEXT NOT NULL,
            base_volume REAL NOT NULL,
            factor REAL NOT NULL,
            volume REAL NOT NULL
        );
        """
    )

    # Otvallar (nom + km)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS otvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            length REAL
        );
        """
    )

    # Zayavkalar
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            day TEXT NOT NULL,
            excavator TEXT NOT NULL,
            text TEXT NOT NULL
        );
        """
    )

    # Ж/Р – lokomotiv bo‘yicha объём (UTT ga qo‘shilmaydi)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS jr_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            day TEXT NOT NULL,
            loco TEXT NOT NULL,
            volume REAL NOT NULL
        );
        """
    )

    conn.commit()
    conn.close()

    ensure_default_otvals()


def ensure_default_otvals():
    """Standart otvallarni borligini tekshirib, yo‘q bo‘lsa qo‘shadi."""
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


# =======================
#  BelAZ logikasi
# =======================

def get_volume_by_truck_id(truck_id: int):
    """
    0–99    -> 42 м³ (130т)
    100–140 -> 75 м³ (220т)
    200–205 -> 50 м³ (240т)
    """
    if 0 <= truck_id <= 99:
        return "130т", 42.0
    elif 100 <= truck_id <= 140:
        return "220т", 75.0
    elif 200 <= truck_id <= 205:
        return "240т", 50.0
    else:
        return "unknown", 0.0


# =======================
#  DB funksiyalar – hodkalar
# =======================

def insert_record(excavator: str, otval: str, truck_id: int, is_half: bool):
    conn = get_connection()
    cur = conn.cursor()

    truck_class, base_volume = get_volume_by_truck_id(truck_id)
    if base_volume == 0.0:
        conn.close()
        return None, "Объём для этого БелАЗа не определён (номер вне диапазона)."

    factor = 0.5 if is_half else 1.0
    volume = base_volume * factor

    now = get_now_tashkent()
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
    """Bitta ekskavator bo‘yicha kunlik hodkalar (detal)."""
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


def get_daily_details_all(day_str: str) -> pd.DataFrame:
    """Kun bo‘yicha barcha hodkalar (barcha ekskavatorlar, barcha otvallar)."""
    conn = get_connection()
    query = """
        SELECT ts, day, excavator, otval, truck_id, truck_class,
               base_volume, factor, volume
        FROM records
        WHERE day = ?
        ORDER BY ts;
    """
    df = pd.read_sql_query(query, conn, params=(day_str,))
    conn.close()
    return df


def get_daily_aggregated_all(day_str: str) -> pd.DataFrame:
    """Kun bo‘yicha agregat: day / exc / otval / truck_id."""
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


# =======================
#  DB – otvals
# =======================

def get_otvals_table() -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql_query("SELECT id, name, length FROM otvals ORDER BY id;", conn)
    conn.close()
    return df


def get_otval_length(name: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT length FROM otvals WHERE name = ?;", (name,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    return row[0]


def upsert_otval(name: str, length):
    conn = get_connection()
    cur = conn.cursor()
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


def delete_otval(name: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM otvals WHERE name = ?;", (name,))
    conn.commit()
    conn.close()


# =======================
#  DB – ZAYAVKI
# =======================

def insert_request(excavator: str, text: str):
    conn = get_connection()
    cur = conn.cursor()
    now = get_now_tashkent()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    day = now.strftime("%Y-%m-%d")
    cur.execute(
        """
        INSERT INTO requests (ts, day, excavator, text)
        VALUES (?, ?, ?, ?)
        """,
        (ts, day, excavator, text)
    )
    conn.commit()
    conn.close()


def get_requests_for_excavator(day_str: str, excavator: str) -> pd.DataFrame:
    conn = get_connection()
    query = """
        SELECT id, ts, day, excavator, text
        FROM requests
        WHERE day = ? AND excavator = ?
        ORDER BY ts;
    """
    df = pd.read_sql_query(query, conn, params=(day_str, excavator))
    conn.close()
    return df


def get_requests_by_day(day_str: str) -> pd.DataFrame:
    conn = get_connection()
    query = """
        SELECT id, ts, day, excavator, text
        FROM requests
        WHERE day = ?
        ORDER BY excavator, ts;
    """
    df = pd.read_sql_query(query, conn, params=(day_str,))
    conn.close()
    return df


# =======================
#  DB – Ж/Р
# =======================

def insert_jr(loco: str, volume: float):
    conn = get_connection()
    cur = conn.cursor()
    now = get_now_tashkent()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    day = now.strftime("%Y-%m-%d")
    cur.execute(
        """
        INSERT INTO jr_records (ts, day, loco, volume)
        VALUES (?, ?, ?, ?)
        """,
        (ts, day, loco, volume)
    )
    conn.commit()
    conn.close()


def get_jr_by_day(day_str: str) -> pd.DataFrame:
    conn = get_connection()
    query = """
        SELECT id, ts, day, loco, volume
        FROM jr_records
        WHERE day = ?
        ORDER BY ts;
    """
    df = pd.read_sql_query(query, conn, params=(day_str,))
    conn.close()
    return df


# =======================
#  Otval summary (records)
# =======================

def get_otval_summary(day_str: str) -> pd.DataFrame:
    """
    Kun bo‘yicha otval + excavator kesimi:
    faqat records jadvalidan (BelAZ + Хоз. работа otvallari).
    """
    conn = get_connection()
    df_rec = pd.read_sql_query(
        "SELECT day, otval, excavator, volume FROM records WHERE day = ?;",
        conn,
        params=(day_str,)
    )
    df_otvals = pd.read_sql_query(
        "SELECT name, length FROM otvals;",
        conn
    )
    conn.close()

    if df_rec.empty:
        return pd.DataFrame(columns=["day", "otval", "excavator", "obem", "length"])

    df_all = (
        df_rec
        .groupby(["day", "otval", "excavator"], as_index=False)["volume"]
        .sum()
    )
    df_all = df_all.rename(columns={"volume": "obem"})

    if not df_otvals.empty:
        df_all = df_all.merge(
            df_otvals.rename(columns={"name": "otval"}),
            how="left",
            on="otval"
        )
        df_all = df_all.rename(columns={"length": "length"})
    else:
        df_all["length"] = None

    return df_all


# =======================
#  UI config
# =======================

EXCAVATORS = [
    "1Y", "2Y",
    "13Y",
    "18Y", "19Y", "20Y", "21Y", "22Y", "23Y", "24Y", "25Y", "26Y", "27Y",
    "28Y", "29Y", "30Y", "31Y", "32Y"
]  # Y4 olib tashlangan


def init_session_state():
    if "selected_excavator" not in st.session_state:
        st.session_state["selected_excavator"] = None
    if "selected_otval" not in st.session_state:
        st.session_state["selected_otval"] = None
    if "is_admin" not in st.session_state:
        st.session_state["is_admin"] = False
    if "mode" not in st.session_state:
        st.session_state["mode"] = None  # "pogruzki" yoki "zayavki"


# =======================
#  MAIN
# =======================

def main():
    st.set_page_config(page_title='Карьер "БАРАКАЛИ"- @SJ8696', layout="wide")
    init_db()
    init_session_state()

    # ------------ HEADER ------------
    hcol1, hcol2 = st.columns([1.2, 3])
    with hcol1:
        st.image(LOGO_URL, use_container_width=True)
    with hcol2:
        st.markdown(
            """
            <h2 style="margin-bottom:0;">Карьер "БАРАКАЛИ"- @SJ8696</h2>
            <h4 style="margin-top:4px;">Учёт ходок БелАЗов по экскаваторам</h4>
            """,
            unsafe_allow_html=True,
        )

    st.divider()

    # ------------ ADMIN LOGIN ------------
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
    mode = st.session_state["mode"]

    # ------------ EXCAVATOR TANLASH ------------
    if selected_excavator is None:
        st.subheader("Выберите экскаватор")

        cols = st.columns(3)
        for i, exc in enumerate(EXCAVATORS):
            col = cols[i % 3]
            if col.button(exc, use_container_width=True):
                st.session_state["selected_excavator"] = exc
                st.session_state["selected_otval"] = None
                st.session_state["mode"] = None
                st.rerun()
        return

    st.markdown(f"### Экскаватор: **{selected_excavator}**")
    if st.button("⏪ Сменить экскаватор"):
        st.session_state["selected_excavator"] = None
        st.session_state["selected_otval"] = None
        st.session_state["mode"] = None
        st.rerun()

    st.divider()

    # ------------ MODE TANLASH: POGRUZKI / ZAYAVKI ------------
    if mode is None:
        st.subheader("Выберите режим работы")
        mcol1, mcol2 = st.columns(2)
        with mcol1:
            if st.button("🚚 Погрузки", use_container_width=True):
                st.session_state["mode"] = "pogruzki"
                st.rerun()
        with mcol2:
            if st.button("📋 Заявки", use_container_width=True):
                st.session_state["mode"] = "zayavki"
                st.rerun()
        return

    # ------------ ZAYAVKI MODE ------------
    if mode == "zayavki":
        st.subheader(f"Заявки по экскаватору {selected_excavator}")

        today = date.today()
        selected_day = st.date_input("Дата заявок", value=today, key="zayavki_date")
        day_str = selected_day.strftime("%Y-%m-%d")

        st.markdown("#### Создать новую заявку")
        with st.form("zayavka_form", clear_on_submit=True):
            text = st.text_area(
                "Текст заявки (запчасти, материалы, количество и т.п.)",
                placeholder="Например: 2 шт. ковшевые зубья, 4 шт. шланги, 1 шт. фильтр...",
                height=150
            )
            submitted = st.form_submit_button("💾 Сохранить заявку")

        if submitted:
            clean_text = text.strip()
            if not clean_text:
                st.error("Нельзя сохранить пустую заявку.")
            else:
                insert_request(selected_excavator, clean_text)
                st.success("Заявка сохранена.")
                st.rerun()

        st.markdown(f"#### Заявки за {day_str}")
        df_req = get_requests_for_excavator(day_str, selected_excavator)
        if df_req.empty:
            st.info("Заявок за выбранную дату нет.")
        else:
            df_req_view = df_req.copy()
            df_req_view = df_req_view.rename(columns={
                "day": "Дата",
                "ts": "Время",
                "excavator": "Экскаватор",
                "text": "Заявка",
            })
            df_req_view = df_req_view[["Дата", "Время", "Экскаватор", "Заявка"]]
            st.dataframe(df_req_view, use_container_width=True)

        st.markdown("---")
        st.markdown("Если нужно перейти к учёту ходок БелАЗов:")
        if st.button("➡️ Перейти в режим погрузки"):
            st.session_state["mode"] = "pogruzki"
            st.rerun()

        return  # zayavki uchun qolgan kod kerak emas

    # ------------ POGRUZKI MODE ------------

    otvals_df = get_otvals_table()

    # OTVAL TANLASHGAChA: km o‘zgartirish + yangi Хоз. работа + Ж/Р
    if selected_otval is None:
        st.subheader("Выберите отвал / режим для погрузки")

        # 1) Masofani o‘zgartirish + jadval + Хоз. работа yaratish
        with st.expander("Указать расстояние до отвала (км) / хоз. работы", expanded=False):
            if otvals_df.empty:
                st.info("Отвалов пока нет. Администратор может добавить их в admin panel.")
            else:
                name_select = st.selectbox(
                    "Выберите отвал для редактирования расстояния",
                    otvals_df["name"].tolist(),
                    key="hoz_select_name"
                )
                len_str = st.text_input(
                    "Длина этого отвала (км)",
                    key="hoz_len_input",
                    placeholder="Например: 2.5"
                )
                if st.button("💾 Сохранить расстояние для отвала", key="hoz_save_len_btn"):
                    if not len_str.strip():
                        st.error("Введите длину (км).")
                    else:
                        try:
                            length_val = float(len_str.replace(",", "."))
                        except ValueError:
                            st.error("Длина должна быть числом.")
                        else:
                            upsert_otval(name_select, length_val)
                            st.success("Длина отвала обновлена.")
                            st.rerun()

                st.markdown("##### Текущие отвалы и расстояния")
                show_df = otvals_df.copy()
                show_df = show_df.rename(columns={
                    "id": "ID",
                    "name": "Отвал",
                    "length": "Длина, км"
                })
                st.dataframe(show_df, use_container_width=True)

            st.markdown("---")
            st.markdown("**Добавить хоз. работу (как отвал)**")
            hw_name = st.text_input(
                "Название хоз. работы / отвала",
                key="hw_new_name",
                placeholder="Например: Хоз. работа 1"
            )
            hw_len_str = st.text_input(
                "Длина (км) для хоз. работы",
                key="hw_new_len",
                placeholder="Например: 1.8"
            )
            if st.button("➕ Сохранить хоз. работу как отвал", key="btn_add_hw_as_otval"):
                name_clean = hw_name.strip()
                if not name_clean:
                    st.error("Название хоз. работы обязательно.")
                else:
                    if hw_len_str.strip() == "":
                        length_val = None
                    else:
                        try:
                            length_val = float(hw_len_str.replace(",", "."))
                        except ValueError:
                            st.error("Длина должна быть числом.")
                            length_val = None
                    if hw_len_str.strip() == "" or length_val is not None:
                        upsert_otval(name_clean, length_val)
                        st.success("Хоз. работа добавлена как отвал.")
                        st.rerun()

        st.markdown("### Отвалы")

        cols = st.columns(2)
        for i, row in otvals_df.iterrows():
            name = row["name"]
            length = row["length"]
            if length is not None:
                label = f"{name} ({length} км)"
            else:
                label = name
            col = cols[i % 2]
            if col.button(label, use_container_width=True):
                st.session_state["selected_otval"] = name
                st.rerun()

        st.markdown("### Специальные режимы")

        sp_cols = st.columns(2)
        with sp_cols[0]:
            if st.button("Ж/Р", use_container_width=True):
                st.session_state["selected_otval"] = OTVAL_JR
                st.rerun()

        return

    # OTVAL TANLANGAN – special yoki oddiy
    is_jr = (selected_otval == OTVAL_JR)

    if is_jr:
        otval_label = "Ж/Р"
    else:
        otval_len = get_otval_length(selected_otval)
        if otval_len is not None:
            otval_label = f"{selected_otval} ({otval_len} км)"
        else:
            otval_label = selected_otval

    st.markdown(f"**Режим / отвал:** {otval_label}")
    change_otval_col1, change_otval_col2 = st.columns(2)
    with change_otval_col1:
        if st.button("⏪ Сменить отвал / режим"):
            st.session_state["selected_otval"] = None
            st.rerun()
    with change_otval_col2:
        if st.button("📋 Перейти в заявки"):
            st.session_state["mode"] = "zayavki"
            st.session_state["selected_otval"] = None
            st.rerun()

    st.divider()

    # ========== TABLAR ==========
    tab1, tab2 = st.tabs(["📝 Ввод (для машиниста)", "📊 Общий свод / Admin"])

    # ---------- TAB 1: Vvod ----------
    with tab1:
        today_str = date.today().strftime("%Y-%m-%d")

        # === 1) Ж/Р rejimi ===
        if is_jr:
            st.subheader("Ж/Р – учёт по локомотивам")

            with st.form("jr_form_mach", clear_on_submit=True):
                col_j1, col_j2 = st.columns(2)
                with col_j1:
                    loco = st.text_input("Номер локомотива", placeholder="Например: 001, 23А и т.п.")
                with col_j2:
                    vol_str = st.text_input("Объём, м³", placeholder="Например: 120.5")

                jr_submit = st.form_submit_button("💾 Сохранить Ж/Р")

            if jr_submit:
                loco_clean = loco.strip()
                vol_clean = vol_str.strip()
                if not loco_clean or not vol_clean:
                    st.error("Укажите и номер локомотива, и объём.")
                else:
                    try:
                        vol_val = float(vol_clean.replace(",", "."))
                    except ValueError:
                        st.error("Объём должен быть числом.")
                    else:
                        insert_jr(loco_clean, vol_val)
                        st.success("Ж/Р запись сохранена.")

            st.markdown(f"#### Ж/Р за {today_str}")
            df_jr_today = get_jr_by_day(today_str)
            if df_jr_today.empty:
                st.info("Ж/Р записей за сегодня нет.")
            else:
                df_jr_view = df_jr_today.copy()
                df_jr_view = df_jr_view.rename(columns={
                    "day": "Дата",
                    "ts": "Время",
                    "loco": "№ локомотива",
                    "volume": "Объём, м³",
                })
                df_jr_view = df_jr_view[["Дата", "Время", "№ локомотива", "Объём, м³"]]
                st.dataframe(df_jr_view, use_container_width=True)

        # === 2) Oddiy otval – BelAZ hodkalar ===
        else:
            st.subheader(f"Новая ходка — {selected_excavator}, {otval_label}")

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
                            f"Ходка сохранена: экскаватор {selected_excavator} | отвал: {otval_label} | "
                            f"БелАЗ №{truck_id} | "
                            f"{'0.5 загрузки' if is_half else 'полная загрузка'} | "
                            f"{volume:.2f} м³"
                        )

            # Mashinist uchun — bugungi hodkalar (faqat BelAZ)
            st.markdown(f"### Сегодняшние ходки ({today_str}) по экскаватору {selected_excavator}")

            df_ex_today = get_daily_records(today_str, selected_excavator)

            if df_ex_today.empty:
                st.info("Сегодня пока нет сохранённых ходок для этого экскаватора.")
            else:
                df_ex_today = df_ex_today.copy()
                df_ex_today["xodka"] = range(1, len(df_ex_today) + 1)

                df_ex_view = df_ex_today.rename(columns={
                    "truck_id": "Номер БелАЗа",
                    "volume": "Объём, м³",
                    "day": "Дата",
                    "ts": "Время",
                    "excavator": "Экскаватор",
                    "otval": "Отвал",
                    "truck_class": "Класс БелАЗа",
                    "base_volume": "Базовый объём, м³",
                    "factor": "Коэффициент",
                    "xodka": "Ходка №",
                })

                df_ex_view = df_ex_view[
                    ["Дата", "Время", "Экскаватор", "Отвал", "Номер БелАЗа",
                     "Класс БелАЗа", "Базовый объём, м³", "Коэффициент", "Объём, м³", "Ходка №"]
                ]
                st.dataframe(df_ex_view, use_container_width=True)

    # ---------- TAB 2: Admin / umumiy svod ----------
    with tab2:
        st.subheader("Общий свод по всем экскаваторам")

        today = date.today()
        selected_day = st.date_input("Дата свода", value=today, key="master_date")
        day_str = selected_day.strftime("%Y-%m-%d")

        st.markdown(f"### Дата: **{day_str}**")

        df_all_agg = get_daily_aggregated_all(day_str)

        if df_all_agg.empty:
            st.info("Нет данных за выбранную дату по всем экскаваторам.")
        else:
            df_all_view = df_all_agg.rename(columns={
                "day": "Дата",
                "excavator": "Экскаватор",
                "otval": "Отвал",
                "truck_id": "Номер БелАЗа",
                "trips": "Количество ходок",
                "obem": "Объём, м³",
            })

            total_trips_all = int(df_all_agg["trips"].sum())
            total_obem_all = float(df_all_agg["obem"].sum())

            st.markdown("#### Агрегированный свод (день / экскаватор / отвал / БелАЗ)")
            st.dataframe(df_all_view, use_container_width=True)

            col_a, col_b = st.columns(2)
            with col_a:
                st.metric("Общее количество ходок (все экскаваторы)", total_trips_all)
            with col_b:
                st.metric("Общий объём (м³) по всем экскаваторам", f"{total_obem_all:.2f}")

        st.divider()
        st.markdown("### 🔐 Admin panel")

        if not is_admin:
            st.info("Для доступа к admin panel введите верный admin code сверху.")
            return

        st.success("Админ режим активен.")

        # --- Otvallar bo‘yicha svod ekranda (records) ---
        st.markdown("#### Свод по отвалам (отвал + экскаватор, объём) для экрана")
        df_otval_full = get_otval_summary(day_str)

        if df_otval_full.empty:
            st.info("Нет данных по отвалам за выбранную дату.")
        else:
            df_otval_full_view = df_otval_full.rename(columns={
                "day": "Дата",
                "otval": "Отвал",
                "excavator": "Экскаватор",
                "obem": "Объём, м³",
                "length": "Длина отвала, км",
            })
            st.dataframe(df_otval_full_view, use_container_width=True)

        st.divider()
        st.markdown("#### 📥 Экспорт отчётов (погрузки / заявки)")

        # --- Pogruzki Excel (BelAZ hodkalar, sana+vaqt bitta ustunda) ---
        df_details = get_daily_details_all(day_str)

        if df_details.empty:
            st.info("Нет данных по погрузкам за выбранную дату (для Excel).")
        else:
            df_det_view = df_details.copy()
            # Sana + vaqt bitta ustun
            df_det_view["Дата/Время"] = df_det_view["ts"]

            df_det_view = df_det_view.rename(columns={
                "excavator": "Экскаватор",
                "otval": "Отвал",
                "truck_id": "Номер БелАЗа",
                "truck_class": "Класс БелАЗа",
                "base_volume": "Базовый объём, м³",
                "factor": "Коэффициент",
                "volume": "Объём, м³",
            })

            df_det_view = df_det_view[
                ["Дата/Время", "Экскаватор", "Отвал", "Номер БелАЗа",
                 "Класс БелАЗа", "Базовый объём, м³", "Коэффициент", "Объём, м³"]
            ]

            total_obem_det = df_det_view["Объём, м³"].sum()
            total_row = {
                "Дата/Время": "",
                "Экскаватор": "УТТ",  # umumiy
                "Отвал": "",
                "Номер БелАЗа": "",
                "Класс БелАЗа": "",
                "Базовый объём, м³": "",
                "Коэффициент": "",
                "Объём, м³": total_obem_det,
            }
            df_det_view_total = pd.concat(
                [df_det_view, pd.DataFrame([total_row])],
                ignore_index=True
            )

            # --- Отвалы sheet: records (shuningdek хоз. работа otvallari) ---
            if not df_otval_full.empty:
                otval_df_simple = (
                    df_otval_full
                    .groupby("otval", as_index=False)["obem"]
                    .sum()
                )
                otval_df_view = otval_df_simple.rename(columns={
                    "otval": "Отвал",
                    "obem": "Объём, м³",
                })
                total_row_otval = {
                    "Отвал": "УТТ",
                    "Объём, м³": otval_df_view["Объём, м³"].sum(),
                }
                otval_df_view = pd.concat(
                    [otval_df_view, pd.DataFrame([total_row_otval])],
                    ignore_index=True
                )
            else:
                otval_df_view = pd.DataFrame(columns=["Отвал", "Объём, м³"])

            # --- Ж/Р jadvali (alohida, UTT ga qo‘shilmaydi) ---
            df_jr_day = get_jr_by_day(day_str)
            if df_jr_day.empty:
                jr_view = pd.DataFrame(columns=["Ж/Р", "№ локомотива", "Объём, м³"])
            else:
                jr_view = df_jr_day.copy()
                jr_view = jr_view.rename(columns={
                    "loco": "№ локомотива",
                    "volume": "Объём, м³",
                })
                jr_view["Ж/Р"] = "Ж/Р"
                jr_view = jr_view[["Ж/Р", "№ локомотива", "Объём, м³"]]

            output_pog = BytesIO()
            with pd.ExcelWriter(output_pog, engine="xlsxwriter") as writer:
                # Sheet 1 – Ходки
                df_det_view_total.to_excel(writer, index=False, sheet_name="Ходки")

                # Sheet 2 – Отвалы (+ Ж/Р pastda)
                otval_df_view.to_excel(writer, index=False, sheet_name="Отвалы")

                if not jr_view.empty:
                    startrow = len(otval_df_view) + 3
                    jr_view.to_excel(
                        writer,
                        index=False,
                        sheet_name="Отвалы",
                        startrow=startrow
                    )

            st.download_button(
                label="⬇️ Скачать Excel погрузок",
                data=output_pog.getvalue(),
                file_name=f"belaz_pogruzki_{day_str}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="download_pogruzki"
            )

        # --- Zayavki Excel ---
        df_req_all = get_requests_by_day(day_str)

        if df_req_all.empty:
            st.info("Нет заявок за выбранную дату (для Excel).")
        else:
            df_req_all_view = df_req_all.copy()
            df_req_all_view = df_req_all_view.rename(columns={
                "day": "Дата",
                "ts": "Время",
                "excavator": "Экскаватор",
                "text": "Заявка",
            })
            df_req_all_view = df_req_all_view[["Дата", "Время", "Экскаватор", "Заявка"]]

            output_zay = BytesIO()
            with pd.ExcelWriter(output_zay, engine="xlsxwriter") as writer:
                df_req_all_view.to_excel(writer, index=False, sheet_name="Заявки")

            st.download_button(
                label="⬇️ Скачать Excel заявок",
                data=output_zay.getvalue(),
                file_name=f"belaz_zayavki_{day_str}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="download_zayavki"
            )

        st.divider()

        # --- OTVAL MANAGEMENT (faqat admin) ---
        st.markdown("#### Управление отвалами")

        df_otvals_table = get_otvals_table()
        st.dataframe(df_otvals_table.rename(columns={
            "id": "ID",
            "name": "Отвал",
            "length": "Длина, км"
        }), use_container_width=True)

        st.markdown("**Добавить / обновить отвал (Admin)**")

        names_list = df_otvals_table["name"].tolist()
        special_new = "— Новый отвал —"
        select_options = [special_new] + names_list

        sel_for_edit = st.selectbox(
            "Выберите существующий отвал или «Новый отвал»",
            select_options,
            key="admin_otval_select"
        )

        new_len_input_admin = st.text_input(
            "Длина отвала (км, можно пусто)",
            key="new_otval_len_admin",
            placeholder="Например: 3.2"
        )

        if sel_for_edit == special_new:
            new_otval_name_admin = st.text_input(
                "Название нового отвала",
                key="new_otval_name_admin",
                placeholder="Например: МОФ-5",
            )
        else:
            new_otval_name_admin = sel_for_edit  # bor otval nomi

        add_col, del_col = st.columns(2)

        with add_col:
            if st.button("💾 Сохранить (добавить/обновить) отвал", key="admin_save_otval"):
                name = new_otval_name_admin.strip()
                if not name:
                    st.error("Название отвала обязательно.")
                else:
                    if new_len_input_admin.strip() == "":
                        length_val = None
                    else:
                        try:
                            length_val = float(new_len_input_admin.replace(",", "."))
                        except ValueError:
                            st.error("Длина должна быть числом (например 3.2).")
                            length_val = None

                    if new_len_input_admin.strip() == "" or length_val is not None:
                        upsert_otval(name, length_val)
                        st.success("Отвал сохранён (Admin).")
                        st.rerun()

        with del_col:
            st.markdown("**Удалить отвал**")
            if df_otvals_table.empty:
                st.write("Отвалов нет.")
            else:
                del_name = st.selectbox(
                    "Выберите отвал для удаления",
                    df_otvals_table["name"].tolist(),
                    key="delete_otval_select"
                )
                if st.button("🗑 Удалить отвал", type="secondary", key="btn_del_otval"):
                    delete_otval(del_name)
                    st.warning(f"Отвал «{del_name}» удалён. История в записях сохранена.")
                    st.rerun()


if __name__ == "__main__":
    main()
