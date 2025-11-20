import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, date
from io import BytesIO

DB_FILE = "belaz.db"

LOGO_URL = "https://i.pinimg.com/originals/c2/75/23/c27523fa667c63ac05b6a4b89befa0f1.png"


def get_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    return conn

def init_db():
    """Создаёт таблицу, если её нет. НИЧЕГО НЕ УДАЛЯЕТ."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,          -- время
            day TEXT NOT NULL,         -- дата (YYYY-MM-DD)
            excavator TEXT NOT NULL,   -- экскаватор (1Y, 2Y, Y4, 18Y...)
            otval TEXT NOT NULL,       -- отвал
            truck_id INTEGER NOT NULL, -- номер БелАЗа
            truck_class TEXT NOT NULL, -- тип: 130т / 220т / 240т / unknown
            base_volume REAL NOT NULL, -- базовый объём м³ (42/75/50)
            factor REAL NOT NULL,      -- коэффициент (1.0 или 0.5)
            volume REAL NOT NULL       -- фактический объём м³
        );
        """
    )

    conn.commit()
    conn.close()


def get_volume_by_truck_id(truck_id: int):
    """
    Объём (м³) по номеру БелАЗа:
    0–99    → 42 м³   (130 т)
    100–140 → 75 м³   (220 т)
    200–205 → 80 м³   (240 т)
    """
    if 0 <= truck_id <= 99:
        return "130т", 42.0
    elif 100 <= truck_id <= 140:
        return "220т", 75.0
    elif 200 <= truck_id <= 205:
        return "240т", 80.0
    else:
        return "unknown", 0.0


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


EXCAVATORS = [
    "1Y", "2Y", "Y4",
    "13Y",
    "18Y", "19Y", "20Y", "21Y", "22Y", "23Y", "24Y", "25Y", "26Y", "27Y",
    "28Y", "29Y", "30Y", "31Y", "32Y"
]

OTVALS = [
    "Перегруз отвал",
    "2Ё ближний отвал",
    "2Ё дальний отвал",
    "А4 окисленный отвал",
]


def init_session_state():
    if "selected_excavator" not in st.session_state:
        st.session_state["selected_excavator"] = None
    if "selected_otval" not in st.session_state:
        st.session_state["selected_otval"] = None


def main():
    st.set_page_config(page_title="Карьер «Баракали Ёшлик» – БелАЗ учёт", layout="wide")
    init_db()
    init_session_state()

    header_col1, header_col2 = st.columns([1, 5])
    with header_col1:
        try:
            st.image(LOGO_URL, width=140)  
        except Exception:
            st.write("⛏️")
    with header_col2:
        st.markdown(
            "<h2 style='margin-bottom:0;'>Карьер «Баракали Ёшлик»</h2>"
            "<h4 style='margin-top:0;'>Учёт ходок БелАЗов по экскаваторам</h4>",
            unsafe_allow_html=True
        )

    st.divider()

    selected_excavator = st.session_state["selected_excavator"]
    selected_otval = st.session_state["selected_otval"]

    if selected_excavator is None:
        st.subheader("Выберите экскаватор")

        cols = st.columns(4)
        for i, exc in enumerate(EXCAVATORS):
            col = cols[i % 4]
            if col.button(exc, use_container_width=True):
                st.session_state["selected_excavator"] = exc
                st.session_state["selected_otval"] = None
                st.rerun()
        return  

    st.markdown(f"### Экскаватор: **{selected_excavator}**")
    if st.button("⏪ Сменить экскаватор"):
        st.session_state["selected_excavator"] = None
        st.session_state["selected_otval"] = None
        st.rerun()

    st.divider()

    if selected_otval is None:
        st.subheader("Выберите отвал")

        cols = st.columns(2)
        for i, otv in enumerate(OTVALS):
            col = cols[i % 2]
            if col.button(otv, use_container_width=True):
                st.session_state["selected_otval"] = otv
                st.rerun()
        return


    st.markdown(f"**Отвал:** {selected_otval}")
    change_otval_col1, change_otval_col2 = st.columns(2)
    with change_otval_col1:
        if st.button("⏪ Сменить отвал"):
            st.session_state["selected_otval"] = None
            st.rerun()

    st.divider()


    tab1, tab2 = st.tabs(["📝 Ввод ходки (для машиниста)", "📊 Общий свод (для мастера)"])

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

    with tab2:
        st.subheader("Общий свод по всем экскаваторам (для мастера)")

        today = date.today()
        selected_day = st.date_input("Выберите дату", value=today, key="master_date")
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

            summary_row = {
                "day": "",
                "excavator": "ИТОГО",
                "otval": "",
                "belaz_no": "",
                "trips": total_trips_all,
                "obem": total_obem_all
            }
            df_all_with_total = pd.concat(
                [df_all, pd.DataFrame([summary_row])],
                ignore_index=True
            )

            st.markdown("#### Агрегированный свод (день / экскаватор / отвал / БелАЗ)")
            st.dataframe(df_all_with_total, use_container_width=True)

            col_a, col_b = st.columns(2)
            with col_a:
                st.metric("Общее количество ходок (все экскаваторы)", int(total_trips_all))
            with col_b:
                st.metric("Общий объём (м³) по всем экскаваторам", f"{total_obem_all:.2f}")

    
            st.markdown("### 📥 Экспорт общего отчёта (1 Excel-файл для всех экскаваторов)")

            output = BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                df_all_with_total.to_excel(writer, index=False, sheet_name="Данные")

            st.download_button(
                label="⬇️ Скачать общий Excel-файл",
                data=output.getvalue(),
                file_name=f"belaz_all_{day_str}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )


if __name__ == "__main__":
    main()
