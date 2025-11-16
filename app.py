import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, date
from io import BytesIO

DB_FILE = "belaz.db"

def get_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    return conn

def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            day TEXT NOT NULL,
            excavator TEXT NOT NULL,
            truck_id INTEGER NOT NULL,
            capacity INTEGER NOT NULL,
            factor REAL NOT NULL,
            tonnage REAL NOT NULL
        );
        """
    )

    conn.commit()
    conn.close()
def get_capacity_by_truck_id(truck_id: int):
    """
    Тоннаж по номеру БелАЗа:
    0–99    -> 130 т
    100–140 -> 220 т
    200–205 -> 240 т
    """
    if 0 <= truck_id <= 99:
        return 130
    elif 100 <= truck_id <= 140:
        return 220
    elif 200 <= truck_id <= 205:
        return 240
    else:
        return None
    
def insert_record(excavator: str, truck_id: int, is_half: bool):
    conn = get_connection()
    cur = conn.cursor()

    capacity = get_capacity_by_truck_id(truck_id)
    if capacity is None:
        conn.close()
        return None, "Для этого номера БелАЗа тоннаж не определён."

    factor = 0.5 if is_half else 1.0
    tonnage = capacity * factor

    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    day = now.strftime("%Y-%m-%d")

    cur.execute(
        """
        INSERT INTO records (ts, day, excavator, truck_id, capacity, factor, tonnage)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (ts, day, excavator, truck_id, capacity, factor, tonnage)
    )

    conn.commit()
    conn.close()

    return tonnage, None

def get_daily_summary(day_str: str) -> pd.DataFrame:
    conn = get_connection()
    query = """
        SELECT excavator,
               COUNT(*) AS trips,
               SUM(tonnage) AS total_tonnage
        FROM records
        WHERE day = ?
        GROUP BY excavator
        ORDER BY excavator
    """
    df = pd.read_sql_query(query, conn, params=(day_str,))
    conn.close()
    return df

def get_daily_details(day_str: str) -> pd.DataFrame:
    conn = get_connection()
    query = """
        SELECT ts, day, excavator, truck_id, capacity, factor, tonnage
        FROM records
        WHERE day = ?
        ORDER BY ts
    """
    df = pd.read_sql_query(query, conn, params=(day_str,))
    conn.close()
    return df
def main():
    st.set_page_config(page_title="БелАЗ – учёт ходок", layout="wide")
    st.title("🚜 Учет ходок БелАЗов по экскаваторам")

    init_db()

    tab1, tab2 = st.tabs(["📝 Добавить ходку", "📊 Отчёт / Excel"])
    with tab1:
        st.subheader("Добавление новой ходки")

        with st.form("hodka_form", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)

            with col1:
                excavators = [f"Э{i}" for i in range(1, 14)]
                excavator = st.selectbox("Выберите экскаватор", excavators)

            with col2:
                truck_id = st.number_input("Номер БелАЗа", min_value=0, max_value=9999, step=1)

            with col3:
                is_half = st.checkbox("Полупустая (после ремонта, 0.5 загрузки)")

            submitted = st.form_submit_button("💾 Сохранить ходку")

        if submitted:
            tonnage, error = insert_record(excavator, int(truck_id), is_half)

            if error:
                st.error("❌ " + error)
            else:
                st.success(
                    f"Ходка сохранена: {excavator} | БелАЗ №{truck_id} | "
                    f"{'0.5 загрузки' if is_half else 'полная загрузка'} | {tonnage} т"
                )
    with tab2:
        st.subheader("Ежедневный отчёт и экспорт в Excel")

        today = date.today()
        selected_day = st.date_input("Выберите дату", value=today)
        day_str = selected_day.strftime("%Y-%m-%d")

        st.markdown(f"### Дата: **{day_str}**")

        summary_df = get_daily_summary(day_str)
        details_df = get_daily_details(day_str)

        if summary_df.empty and details_df.empty:
            st.info("Нет данных за выбранную дату.")
        else:
            col1, col2 = st.columns(2)

            with col1:
                st.markdown("#### Итог по экскаваторам")
                st.dataframe(summary_df, use_container_width=True)

            with col2:
                st.markdown("#### Подробный список ходок")
                st.dataframe(details_df, use_container_width=True)

            st.markdown("### 📥 Экспорт в Excel")

            output = BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                summary_df.to_excel(writer, index=False, sheet_name="Сводка")
                details_df.to_excel(writer, index=False, sheet_name="Детали")

            excel_data = output.getvalue()

            st.download_button(
                label="⬇️ Скачать Excel-файл",
                data=excel_data,
                file_name=f"belaz_report_{day_str}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

if __name__ == "__main__":
    main()
