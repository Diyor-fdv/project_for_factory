import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, date
from io import BytesIO

DB_FILE = "belaz.db"


# =====================================
#   SQLite соединение + создание таблицы
# =====================================

def get_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    return conn

def init_db():
    """Создаёт таблицу, если её нет. Ничего не удаляет!"""
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
            truck_class TEXT NOT NULL,
            base_volume REAL NOT NULL,
            factor REAL NOT NULL,
            volume REAL NOT NULL,
            otval TEXT
        );
        """
    )

    conn.commit()
    conn.close()


# =====================================
#   Бизнес-логика: объём по номеру БелАЗа
# =====================================

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


# =====================================
#   Работа с БД
# =====================================

def insert_record(excavator: str, truck_id: int, is_half: bool, otval: str):
    conn = get_connection()
    cur = conn.cursor()

    truck_class, base_volume = get_volume_by_truck_id(truck_id)

    if base_volume == 0.0:
        conn.close()
        return None, "Объём для этого БелАЗа не определён."

    factor = 0.5 if is_half else 1.0
    volume = base_volume * factor

    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    day = now.strftime("%Y-%m-%d")

    cur.execute(
        """
        INSERT INTO records
        (ts, day, excavator, truck_id, truck_class, base_volume, factor, volume, otval)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (ts, day, excavator, truck_id, truck_class, base_volume, factor, volume, otval)
    )

    conn.commit()
    conn.close()
    return volume, None


def get_daily_summary(day_str: str) -> pd.DataFrame:
    conn = get_connection()
    query = """
        SELECT excavator,
               COUNT(*) AS trips,
               SUM(volume) AS total_volume
        FROM records
        WHERE day = ?
        GROUP BY excavator
        ORDER BY excavator;
    """
    df = pd.read_sql_query(query, conn, params=(day_str,))
    conn.close()
    return df


def get_daily_details(day_str: str) -> pd.DataFrame:
    conn = get_connection()
    query = """
        SELECT id, ts, day, excavator, truck_id, truck_class,
               base_volume, factor, volume, otval
        FROM records
        WHERE day = ?
        ORDER BY ts;
    """
    df = pd.read_sql_query(query, conn, params=(day_str,))
    conn.close()
    return df


# =====================================
#   Streamlit UI
# =====================================

def main():
    st.set_page_config(page_title="БелАЗ – учёт ходок", layout="wide")
    st.title("🚜 Учет ходок БелАЗов по экскаваторам")

    # Создаём БД, если её нет
    init_db()

    tab1, tab2 = st.tabs(["📝 Добавить ходку", "📊 Отчёт / Excel"])

    # ----------- TAB 1: Добавление ходки -----------
    with tab1:
        st.subheader("Добавление новой ходки")

        with st.form("hodka_form", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)

            with col1:
                excavators = [
                    "Ё1", "Ё2", "Ё3",
                    "Ё13",
                    "Ё18", "Ё19", "Ё20", "Ё21", "Ё22", "Ё23", "Ё24", "Ё25", "Ё26", "Ё27"
                ]
                excavator = st.selectbox("Выберите экскаватор", excavators)

            with col2:
                truck_id = st.number_input("Номер БелАЗа", min_value=0, max_value=9999, step=1)

            with col3:
                is_half = st.checkbox("Полупустая (0.5 загрузки)")

            otval = st.text_input(
                "Отвал / расстояние (км, участок и т.п.)",
                placeholder="Например: 2.5 км, участок 3, Северный отвал..."
            )

            submitted = st.form_submit_button("💾 Сохранить ходку")

        if submitted:
            volume, error = insert_record(excavator, int(truck_id), is_half, otval)

            if error:
                st.error("❌ " + error)
            else:
                st.success(
                    f"Ходка сохранена: {excavator} | БелАЗ №{truck_id} | "
                    f"{'0.5 загрузки' if is_half else 'полная загрузка'} | "
                    f"{volume:.2f} м³"
                )

    # ----------- TAB 2: Отчёт и Excel -----------
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
            # Добавляем строку ИТОГО
            total_row = pd.DataFrame([{
                "excavator": "ИТОГО",
                "trips": summary_df["trips"].sum(),
                "total_volume": summary_df["total_volume"].sum()
            }])
            summary_full = pd.concat([summary_df, total_row], ignore_index=True)

            # Нумерация ходок
            details = details_df.copy()
            details["xodka"] = range(1, len(details) + 1)

            # Переименование для Excel
            details_excel = details.rename(columns={
                "truck_id": "belaz_no",
                "volume": "obem"
            })

            col1, col2 = st.columns(2)

            with col1:
                st.markdown("#### Итог по экскаваторам")
                st.dataframe(summary_full, use_container_width=True)

                st.metric("Общий объём за день (м³)", f"{summary_full['total_volume'].iloc[-1]:.2f}")

            with col2:
                st.markdown("#### Подробный список ходок")
                st.dataframe(details_excel, use_container_width=True)

            # -------- Excel Export --------
            st.markdown("### 📥 Экспорт в Excel")

            output = BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                summary_full.to_excel(writer, index=False, sheet_name="Сводка")
                details_excel.to_excel(writer, index=False, sheet_name="Детали")

            st.download_button(
                label="⬇️ Скачать Excel-файл",
                data=output.getvalue(),
                file_name=f"belaz_report_{day_str}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )


if __name__ == "__main__":
    main()
