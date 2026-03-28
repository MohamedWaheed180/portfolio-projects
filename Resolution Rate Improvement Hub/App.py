import streamlit as st
import pandas as pd
import cx_Oracle
import plotly.express as px
import datetime # Added for date handling

# --------------------------------------------------------
# 1. DATABASE CONNECTION SETTINGS
# --------------------------------------------------------

def get_db_connection(user, pwd, host, port, service):
    """Establish and return an Oracle Database connection."""
    dsn = cx_Oracle.makedsn(host, port, service_name=service)
    connection = cx_Oracle.connect(user, pwd, dsn)
    return connection

# --------------------------------------------------------
# 2. SQL QUERIES & MAPPINGS
# --------------------------------------------------------
# Replaced '01-JAN-26' with TO_DATE(:start_date, 'YYYY-MM-DD')
EXTRACT_SQL = """
SELECT 
    w.ticket_id,
    q.ticket_id AS q_ticket_id,
    w.REQUESTER_MAIL,
    w.FUNCTION as ticket_Function,
    w.GROUP_NAME as ticket_Group,
    w.TYPE_OF_REQUEST as TicketType,
    w.ORGANIZATION_NAME,
    w.PRIORITY,
    w.SPECIAL_CASES,
    w.CHILD_TICKET,
    w.TICKET_STATUS,
    w.ticket_subject, 
    CASE 
        WHEN w.ticket_subject LIKE 'Project-%' 
        THEN REGEXP_SUBSTR(w.ticket_subject, '[0-9]+') 
        ELSE NULL 
    END AS PARENT_TICKET_ID,
    emailsys.yyyyyyy As Mailsys_Function #suggest anmae to be avoided real names of the function
FROM 
    Table_Name1 w
LEFT JOIN 
     Table_Name2 q ON w.ticket_id = q.ticket_id
LEFT JOIN 
    Table_Name3 x ON x.USER_REQ_ID = q.USER_REQ AND emailsys.PN_Name = q.PN
LEFT JOIN 
    Table_Name4 y ON x.PARTREQUEST_ID = y.PARTREQUEST_ID
WHERE 
    w.TICKET_STATUS = 'hold'
    AND w.TICKET_SUBMIT_DATE BETWEEN TO_DATE(:start_date, 'YYYY-MM-DD') AND SYSDATE
    AND NOT EXISTS (
        SELECT 1 
        FROM Table_Name2 q_sub
        LEFT JOIN Table_Name3 x_sub 
               ON x_sub.USER_REQ_ID = q_sub.USER_REQ 
              AND emailsys.PN_Name = q_sub.PN
        WHERE q_sub.ticket_id = w.ticket_id
          AND (x_sub.PARTSTATUS_ID NOT IN ('Closed_Corrected_PN','Escalated to Customer','Escalated to customer','Closed')
               OR x_sub.PARTSTATUS_ID IS NULL)
    )
"""

VALID_GROUPS =[
    'Conflict Minerals', 'REACH', 'RoHS', 'Chemical', 
    'Environmental Regulation', 'LIFECYCLE', 'MFG Data', 'Risk Analysis'
]

MAILSYS_MAPPING = {
    'RoHS': 'RoHS', 'China RoHS': 'RoHS', 'REACH': 'REACH', 'SCIP': 'REACH',
    'Animal_Derived_Materials': 'Environmental Regulation', 'Canada_Regulation_SOR': 'Environmental Regulation',
    'IMDS_Chemical': 'Chemical', 'Wire_Bonding': 'Chemical', 'TSCA_Section_PFAS': 'Environmental Regulation', 
    'Halogen free': 'RoHS', 'Conflict_Minerals': 'Conflict Minerals', 'PFAS': 'Environmental Regulation',
    'Reach restriction': 'REACH', 'Rare_Earth': 'Environmental Regulation', 'PFOS': 'Environmental Regulation', 
    'CEPA': 'Environmental Regulation', 'WEEE Status': 'Environmental Regulation', 'LifeCycle': 'LIFECYCLE',
    'Environmental_Manufacture': 'MFG Data', 'PFOA': 'Environmental Regulation', 'Chemical': 'Chemical', 
    'Health_Canada_file_number': 'Environmental Regulation', 'CSCL': 'Environmental Regulation', 
    'Biocidal_Products_Regulation': 'Environmental Regulation', 'EMRT': 'Conflict Minerals', 
    'Persistent Organic Pollutants (POPs)': 'Environmental Regulation', 'GADSL': 'Environmental Regulation', 
    'EU_Packaging': 'Environmental Regulation', 'Canada_PFAS': 'Environmental Regulation', 
    'F_Gases_Regulation': 'Environmental Regulation', 'California_65': 'Environmental Regulation', 
    'TSCA': 'Environmental Regulation', 'EU_MDR': 'Environmental Regulation', 'Latex': 'Environmental Regulation'
}

# --------------------------------------------------------
# 3. CREATE TABLE SQL
# --------------------------------------------------------
CREATE_TABLE_SQL = """
    BEGIN
        EXECUTE IMMEDIATE '
            CREATE TABLE TICKET_HOLD_ANALYSIS (
                TICKET_ID           VARCHAR2(100),
                Q_TICKET_ID         VARCHAR2(100),
                REQUESTER_MAIL      VARCHAR2(255),
                TICKET_FUNCTION     VARCHAR2(255),
                TICKET_GROUP        VARCHAR2(255),
                TICKETTYPE          VARCHAR2(255),
                ORGANIZATION_NAME   VARCHAR2(255),
                PRIORITY            VARCHAR2(50),
                SPECIAL_CASES       VARCHAR2(255),
                CHILD_TICKET        VARCHAR2(100),
                TICKET_STATUS       VARCHAR2(50),
                TICKET_SUBJECT      VARCHAR2(500),
                PARENT_TICKET_ID    VARCHAR2(100)
            )
        ';
    EXCEPTION
        WHEN OTHERS THEN
            IF SQLCODE = -955 THEN NULL; -- Table already exists, do nothing
            ELSE RAISE;
            END IF;
    END;
"""

# --------------------------------------------------------
# 4. CORE FUNCTIONS
# --------------------------------------------------------
def execute_reset(db_user, db_pwd, db_host, db_port, db_srv, start_date):
    try:
        conn = get_db_connection(db_user, db_pwd, db_host, db_port, db_srv)
    except Exception as e:
        return False, f"Connection Failed: {str(e)}"
    try:
        cursor = conn.cursor()
        
        # Pass the date param into cx_oracle safely
        formatted_date = start_date.strftime('%Y-%m-%d')
        cursor.execute(EXTRACT_SQL, {'start_date': formatted_date})
        
        columns = [col[0].upper() for col in cursor.description]
        data = cursor.fetchall()
        df = pd.DataFrame(data, columns=columns)
        
        if df.empty:
            return False, "No data fetched from the source."

        df = df.dropna(subset=['Q_TICKET_ID'])

        mask_invalid_group = ~df['TICKET_GROUP'].isin(VALID_GROUPS)
        mapped_values = df.loc[mask_invalid_group, 'MAILSYS_FUNCTION'].map(MAILSYS_MAPPING)
        df.loc[mask_invalid_group, 'TICKET_GROUP'] = mapped_values.combine_first(df.loc[mask_invalid_group, 'TICKET_GROUP'])
        
        df = df[df['TICKET_GROUP'].isin(VALID_GROUPS)]
        df = df.drop(columns=['MAILSYS_FUNCTION'])
        df = df.drop_duplicates()
        df = df.where(pd.notnull(df), None)

        cursor.execute(CREATE_TABLE_SQL)   
        cursor.execute("TRUNCATE TABLE TICKET_HOLD_ANALYSIS") 
        
        insert_sql = """
            INSERT INTO TICKET_HOLD_ANALYSIS (
                TICKET_ID, Q_TICKET_ID, REQUESTER_MAIL, TICKET_FUNCTION, TICKET_GROUP, 
                TICKETTYPE, ORGANIZATION_NAME, PRIORITY, SPECIAL_CASES, CHILD_TICKET, 
                TICKET_STATUS, TICKET_SUBJECT, PARENT_TICKET_ID
            ) VALUES (:1, :2, :3, :4, :5, :6, :7, :8, :9, :10, :11, :12, :13)
        """
        
        records_to_insert =[tuple(x) for x in df.to_numpy()]
        cursor.executemany(insert_sql, records_to_insert)
        conn.commit()
        
        return True, f"Successfully reset and inserted {len(records_to_insert)} unique rows."
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

def execute_refresh(db_user, db_pwd, db_host, db_port, db_srv):
    try:
        conn = get_db_connection(db_user, db_pwd, db_host, db_port, db_srv)
    except Exception as e:
        return False, f"Connection Failed: {str(e)}"
    try:
        cursor = conn.cursor()
        delete_sql = """
            DELETE FROM TICKET_HOLD_ANALYSIS t
            WHERE EXISTS (
                SELECT 1 
                FROM Table_Name1 w
                WHERE w.ticket_id = t.TICKET_ID 
                  AND w.TICKET_STATUS != 'hold'
            )
        """
        cursor.execute(delete_sql)
        deleted_count = cursor.rowcount
        conn.commit()
        return True, f"Refreshed successfully! Removed {deleted_count} tickets that are no longer on 'hold'."
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

@st.cache_data(ttl=600)
def load_dashboard_data(db_user, db_pwd, db_host, db_port, db_srv):
    """Loads current data using provided credentials."""
    try:
        conn = get_db_connection(db_user, db_pwd, db_host, db_port, db_srv)
        query = "SELECT * FROM TICKET_HOLD_ANALYSIS"
        df = pd.read_sql(query, con=conn)
        conn.close()
        return df
    except Exception as e:
        return pd.DataFrame()

# --------------------------------------------------------
# 5. STREAMLIT GUI DASHBOARD
# --------------------------------------------------------
st.set_page_config(page_title="Ticket Hold Analysis Dashboard", layout="wide")

# --- SIDEBAR: DATABASE CREDENTIALS & FILTERS ---
with st.sidebar:
    st.header("🔌 Database Connection")
    st.markdown("Enter your Oracle credentials below:")
    
    username = st.text_input("Username", value="Sadoon")
    password = st.text_input("Password", value="b7bk", type="password")
    host = st.text_input("Host", value="Blank_Host")
    port = st.text_input("Port", value="Blank_Port")
    service_name = st.text_input("Service Name", value="Blank_Service_Name")
    
    st.divider()
    
    # User Input for Date Parameter
    st.header("📅 Extraction Filters")
    user_start_date = st.date_input("Start Date", value=datetime.date(2026, 1, 1))

    # Check if all fields are filled
    creds_filled = all([username, password, host, port, service_name])
    
    if not creds_filled:
        st.warning("⚠️ Please fill in all database fields to connect.")

st.title("🎯 Resolution Rate Improvement Hub")

if not creds_filled:
    st.warning("⚠️ Please fill in all database fields to connect.")

if creds_filled:
    st.markdown("### Controls")
    col_btn1, col_btn2 = st.columns(2)

    with col_btn1:
        # Pass user_start_date to the reset function
        if st.button("🔄 Reset Data Pipeline", use_container_width=True):
            with st.spinner(f"Extracting tickets from {user_start_date}, cleaning, and inserting..."):
                success, message = execute_reset(username, password, host, port, service_name, user_start_date)
                if success:
                    st.success(message)
                    st.cache_data.clear()
                else:
                    st.error(f"Error: {message}")

    with col_btn2:
        if st.button("⚡ Refresh Ticket Statuses", use_container_width=True):
            with st.spinner("Checking database for released tickets..."):
                success, message = execute_refresh(username, password, host, port, service_name)
                if success:
                    st.success(message)
                    st.cache_data.clear()
                else:
                    st.error(f"Error: {message}")

    st.divider()

    # Load Current Data
    df_dashboard = load_dashboard_data(username, password, host, port, service_name)

    if df_dashboard.empty:
        st.info("The Analysis table is currently empty or cannot be reached. Please check credentials or click '🔄 Reset Data Pipeline'.")
    else:
        st.markdown("### 📥 Export")
        txt_data = df_dashboard.to_csv(sep='\t', index=False)
        st.download_button(
            label="📄 Export Data to TXT File",
            data=txt_data,
            file_name="ticket_hold_analysis.txt",
            mime="text/plain",
            use_container_width=True
        )

        st.markdown("---")

        st.markdown("### Summary Metrics")
        m1, m2, m3, m4 = st.columns(4)

        distinct_parent = df_dashboard['PARENT_TICKET_ID'].nunique()
        distinct_tickets = df_dashboard['TICKET_ID'].nunique()

        child_no_parent = df_dashboard[df_dashboard['PARENT_TICKET_ID'].isna()].shape[0]
        can_be_closed = distinct_parent + child_no_parent

        m1.metric("🎫 Distinct Tickets (Total)", f"{distinct_tickets:,}")
        m2.metric("📌 Distinct Parent Tickets", f"{distinct_parent:,}")
        m3.metric("👶 Child Tickets (No Parent)", f"{child_no_parent:,}")
        m4.metric("✅ Tickets That Can Be Closed", f"{can_be_closed:,}")

        st.markdown("---")

        group_df = df_dashboard.groupby('TICKET_GROUP')['TICKET_ID'].nunique().reset_index()
        group_df.columns =['Ticket Group', 'Ticket Count']
        group_df = group_df.sort_values(by='Ticket Count', ascending=False)

        type_df = df_dashboard.groupby('TICKETTYPE')['TICKET_ID'].nunique().reset_index()
        type_df.columns = ['Ticket Type', 'Ticket Count']
        type_df = type_df.sort_values(by='Ticket Count', ascending=False)

        st.markdown("### 📊 Distribution of Tickets per Group")
        chart_col1, chart_col2 = st.columns(2)

        with chart_col1:
            fig_col = px.bar(
                group_df, x='Ticket Group', y='Ticket Count', 
                text='Ticket Count', color='Ticket Group',
                color_discrete_sequence=px.colors.qualitative.Pastel,
                title="Tickets per Group"
            )
            fig_col.update_layout(showlegend=True, xaxis_title="Ticket Group", yaxis_title="Distinct Tickets")
            st.plotly_chart(fig_col, use_container_width=True)

        with chart_col2:
            fig_pie = px.pie(
                type_df, names='Ticket Type', values='Ticket Count',
                color='Ticket Type', 
                color_discrete_sequence=px.colors.qualitative.Pastel,
                title="Tickets per Type",
                hole=0.3
            )
            fig_pie.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig_pie, use_container_width=True)

        st.markdown("---")

        st.markdown("### 🏢 Tickets by Customer (Organization)")
        
        org_df = df_dashboard.groupby('ORGANIZATION_NAME')['TICKET_ID'].nunique().reset_index()
        org_df.columns =['Organization Name', 'Ticket Count']
        org_df = org_df.sort_values(by='Ticket Count', ascending=False).head(15)
        
        fig_org = px.bar(
            org_df, x='Ticket Count', y='Organization Name', orientation='h',
            text='Ticket Count', color='Organization Name',
            color_discrete_sequence=px.colors.qualitative.Set2,
            title="Top 15 Organizations by Ticket Count"
        )
        fig_org.update_layout(showlegend=False, yaxis={'categoryorder':'total ascending'}, xaxis_title="Distinct Tickets", yaxis_title="Organization")
        st.plotly_chart(fig_org, use_container_width=True)

        with st.expander("🔍 View Raw Cleaned Data"):
            st.dataframe(df_dashboard, use_container_width=True)
else:
    st.info("👈 Please enter your Database credentials in the sidebar to access the dashboard.")