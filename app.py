import io
import json
import re
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="Prospect Explorer", page_icon="🚗", layout="wide")

st.markdown(
    """
    <style>
      .big-title {font-size: 44px; font-weight: 800; letter-spacing:-0.4px;}
      .tiny {opacity:.75; font-size:12px}
      .badge {background:#e5f2ff; color:#1f77b4; padding:2px 8px; border-radius:999px; font-size:12px;}
      .contact-card {border:1px solid #e6e8eb; border-radius:16px; padding:14px; background:white}
      div[data-testid="stHorizontalBlock"] > div {gap: 12px}
      .stTabs [data-baseweb="tab"] {font-size:16px}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="big-title">Prospect Explorer – EV & Sustainability</div>', unsafe_allow_html=True)

# =========================
# Data source
# =========================
st.sidebar.title("Data")
st.sidebar.caption("Upload your Excel/CSV. Map your columns once and explore.")
use_sample = st.sidebar.toggle("Use sample data", value=False)
uploaded = None if use_sample else st.sidebar.file_uploader("Excel (.xlsx) or CSV", type=["xlsx","csv"]) 

# -------------------------
# Loader
# -------------------------
NA_VALS = ["na","n/a","N/A","-","--","" ,"none","None"]

def load_df(file):
    if file is None:
        data = {
            "Name":["Yuko Kani","Tetsuya Suwabe","Yosuke Minami"],
            "Company":["JERA","Eurus Energy","Invenia"],
            "Role":["Global CEO","President & CEO","President & CEO"],
            "Sector Focus":["Offshore wind, solar","Wind, Solar","Solar, Biomass"],
            "Email":["info@jera.co.jp","contact@eurus-energy.com","https://invenia.jp/contact"],
            "Number":["81-3-3272-4631","81-3-5404-5000","81-3-3516-5820"],
            "Country":["Japan","Japan","Japan"],
            "Present in CRM":["Yes","No","No"],
        }
        return pd.DataFrame(data)
    if file.name.lower().endswith(".csv"):
        df = pd.read_csv(file, na_values=NA_VALS, keep_default_na=True)
    else:
        xls = pd.ExcelFile(file)
        sheet = st.sidebar.selectbox("Sheet", xls.sheet_names, index=0)
        df = pd.read_excel(xls, sheet_name=sheet, na_values=NA_VALS, keep_default_na=True)
    for c in df.columns:
        if pd.api.types.is_object_dtype(df[c]):
            df[c] = df[c].astype(str).str.strip()
    return df

try:
    df_raw = load_df(uploaded)
except Exception as e:
    st.error(f"Couldn't read the file. Make sure it's a valid CSV/XLSX. Error: {e}")
    st.stop()

# =========================
# Column mapping
# =========================
st.sidebar.subheader("Columns")

def guess_select(label, options, guesses):
    opts = [None] + list(options)
    lower = [str(o).lower() for o in options]
    g = None
    for cand in guesses:
        if cand.lower() in lower:
            g = options[lower.index(cand.lower())]
            break
    idx = opts.index(g) if g in opts else 0
    return st.sidebar.selectbox(label, opts, index=idx)

name_col    = guess_select("Name*",    df_raw.columns, ["name","full name","contact","person"]) 
company_col = guess_select("Company*", df_raw.columns, ["company","organisation","organization","employer"]) 
role_col    = guess_select("Role",      df_raw.columns, ["role","title","job title","position"]) 
sector_col  = guess_select("Sector Focus", df_raw.columns, ["sector","sector focus","focus","industry"]) 
email_col   = guess_select("Email",     df_raw.columns, ["email","e-mail","mail","contact email"]) 
phone_col   = guess_select("Phone/Number", df_raw.columns, ["phone","mobile","telephone","tel","number","phone number","cell"]) 
country_col = guess_select("Country",   df_raw.columns, ["country","nation","location","country name"]) 
crm_col     = guess_select("Present in CRM", df_raw.columns, ["present in crm","crm","in crm","crm present"]) 

missing = [lbl for lbl,c in {"Name":name_col,"Company":company_col}.items() if not c]
if missing:
    st.warning("Please map required columns: "+", ".join(missing))
    st.stop()

# =========================
# Standardization
# =========================
std = pd.DataFrame({
    "Name":    df_raw[name_col],
    "Company": df_raw[company_col],
    "Role":    df_raw[role_col]    if role_col    else "",
    "Sector":  df_raw[sector_col]  if sector_col  else "",
    "Email":   df_raw[email_col]   if email_col   else "",
    "Phone":   df_raw[phone_col]   if phone_col   else "",
    "Country": df_raw[country_col] if country_col else "",
    "CRM":     df_raw[crm_col]     if crm_col     else "",
})

std = std.astype(str).apply(lambda s: s.str.strip())
std.replace({s: "" for s in NA_VALS}, inplace=True)

# normalize CRM to Yes/No/blank
YES = {"yes","y","true","1","present","in crm","crm","✓","check","checked","x"}
NO  = {"no","n","false","0","absent","not in crm","-",""}
crm_norm = std["CRM"].str.lower().map(lambda x: "Yes" if x in YES else ("No" if x in NO else std.loc[std["CRM"]==x,"CRM"]))
std["CRM"] = crm_norm.fillna("")

# detect real emails (ignore URLs pasted into Email column)
std["EmailClean"] = std["Email"].where(std["Email"].str.contains(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", na=False), "")
std["EmailDomain"] = std["EmailClean"].str.extract(r'@([^>\s,;]+)')[0].str.lower()
std["HasEmail"] = std["EmailClean"].ne("")

# phone presence
std["PhoneClean"] = std["Phone"].str.replace(r"[^+0-9]", "", regex=True)
std["HasPhone"] = std["PhoneClean"].str.len().gt(0)

# infer country from phone codes if Country missing
CODE2CNTRY = {
    "1":"United States/Canada","44":"United Kingdom","49":"Germany","33":"France","39":"Italy","34":"Spain",
    "81":"Japan","82":"South Korea","86":"China","65":"Singapore","61":"Australia","971":"United Arab Emirates","974":"Qatar"
}
missing_country = std["Country"].eq("") & std["PhoneClean"].ne("")
std.loc[missing_country, "Country"] = std.loc[missing_country, "PhoneClean"].apply(lambda p: next((v for k,v in CODE2CNTRY.items() if p.startswith(k)), ""))

# contact type
std["ContactType"] = np.select(
    [std["HasEmail"] & std["HasPhone"], std["HasEmail"], std["HasPhone"], std["Email"].str.startswith("http", na=False)],
    ["Both","Email","Phone","Web form"],
    default="None",
)

# region (simple buckets)
REGION = {
    "Japan":"APAC","China":"APAC","South Korea":"APAC","Singapore":"APAC","Australia":"APAC","United Arab Emirates":"MENA","Qatar":"MENA",
    "Germany":"EMEA","United Kingdom":"EMEA","France":"EMEA","Italy":"EMEA","Spain":"EMEA","United States/Canada":"AMER"
}
std["Region"] = std["Country"].map(REGION).fillna("Other")

# =========================
# Filters
# =========================
st.sidebar.subheader("Filters")
sel_regions   = st.sidebar.multiselect("Region", sorted(std["Region"].unique().tolist()))
sel_countries = st.sidebar.multiselect("Country", sorted([c for c in std["Country"].unique() if c]))
sel_companies = st.sidebar.multiselect("Company", sorted([c for c in std["Company"].unique() if c]))
sel_sector    = st.sidebar.multiselect("Sector Focus", sorted([s for s in std["Sector"].unique() if s]))
role_contains = st.sidebar.text_input("Role contains")
email_contains = st.sidebar.text_input("Email contains")
phone_contains = st.sidebar.text_input("Phone contains")
contact_types = st.sidebar.multiselect("Contact type", ["Email","Phone","Both","Web form","None"], default=["Email","Phone","Both"]) 
crm_filter    = st.sidebar.selectbox("Present in CRM", ["All","Yes","No"], index=0)
preferred_contact = st.sidebar.radio("Preferred contact", ["Auto","Email","Phone"], horizontal=True)

f = std.copy()
if sel_regions:   f = f[f["Region"].isin(sel_regions)]
if sel_countries: f = f[f["Country"].isin(sel_countries)]
if sel_companies: f = f[f["Company"].isin(sel_companies)]
if sel_sector:    f = f[f["Sector"].isin(sel_sector)]
if role_contains: f = f[f["Role"].str.contains(role_contains, case=False, na=False)]
if email_contains: f = f[f["Email"].str.contains(email_contains, case=False, na=False)]
if phone_contains: f = f[f["Phone"].str.contains(phone_contains, case=False, na=False)]
if contact_types: f = f[f["ContactType"].isin(contact_types)]
if crm_filter != "All": f = f[f["CRM"] == crm_filter]

# =========================
# KPIs
# =========================
col1,col2,col3,col4,col5,col6,col7 = st.columns(7)
col1.metric("Prospects", f"{len(f):,}")
col2.metric("Companies", f"{f['Company'].nunique():,}")
col3.metric("With email", int(f['HasEmail'].sum()))
col4.metric("With phone", int(f['HasPhone'].sum()))
col5.metric("Only email", int((f['HasEmail'] & ~f['HasPhone']).sum()))
col6.metric("Only phone", int((~f['HasEmail'] & f['HasPhone']).sum()))
col7.metric("In CRM (Yes)", int((f['CRM']=="Yes").sum()))

# =========================
# Tabs
# =========================
(tab_overview, tab_contacts, tab_visuals, tab_quality, tab_tools) = st.tabs(["Overview","Contacts","Visuals","Data Quality","Tools"])

# helper: preferred contact renderer

def render_contact(email, phone):
    email_ok = isinstance(email,str) and "@" in email
    phone_ok = isinstance(phone,str) and phone.strip() != ""
    if preferred_contact == "Email":
        return f"[{email}](mailto:{email})" if email_ok else (f"[{phone}](tel:{phone})" if phone_ok else "")
    if preferred_contact == "Phone":
        return f"[{phone}](tel:{phone})" if phone_ok else (f"[{email}](mailto:{email})" if email_ok else "")
    if email_ok: return f"[{email}](mailto:{email})"
    if phone_ok: return f"[{phone}](tel:{phone})"
    return ""

with tab_overview:
    st.subheader("Prospect List")
    tbl = f.sort_values(["Region","Country","Company","Name"]).reset_index(drop=True).copy()
    tbl["Contact"] = [render_contact(e,p) for e,p in zip(tbl["EmailClean"], tbl["Phone"])]
    cols = ["Name","Company","Role","Sector","Country","Region","CRM","ContactType","Email","Phone","Contact"]
    tbl["Email"] = tbl["EmailClean"].where(tbl["EmailClean"].ne(""), tbl["Email"])  # show raw URL if no email
    tbl["Email"] = tbl["Email"].apply(lambda x: f"[{x}](mailto:{x})" if isinstance(x,str) and "@" in x else x)
    tbl["Phone"] = tbl["Phone"].apply(lambda x: f"[{x}](tel:{x})" if isinstance(x,str) and x.strip() else x)
    st.data_editor(tbl[cols], hide_index=True, use_container_width=True,
                   column_config={"Email": st.column_config.LinkColumn("Email"),
                                  "Phone": st.column_config.LinkColumn("Phone"),
                                  "Contact": st.column_config.LinkColumn("Contact")})

with tab_contacts:
    st.subheader("Quick contact finder")
    q = st.text_input("Search by name or company")
    dfc = f.copy()
    if q:
        m = dfc["Name"].str.contains(q, case=False, na=False) | dfc["Company"].str.contains(q, case=False, na=False)
        dfc = dfc[m]
    if dfc.empty:
        st.info("No contacts match your search or filters.")
    else:
        for _, row in dfc.iterrows():
            items = []
            if isinstance(row["EmailClean"], str) and row["EmailClean"]:
                items.append(f"📧 <a href=\"mailto:{row['EmailClean']}\">{row['EmailClean']}</a>")
            elif isinstance(row["Email"], str) and row["Email"].startswith("http"):
                items.append(f"🌐 <a href=\"{row['Email']}\" target=\"_blank\">Contact form</a>")
            if isinstance(row["Phone"], str) and row["Phone"].strip():
                items.append(f"📞 <a href=\"tel:{row['Phone']}\">{row['Phone']}</a>")
            contact_line = " · ".join(items) if items else "📭 —"
            st.markdown(
                f"""
                <div class='contact-card'>
                  <div style='display:flex; justify-content:space-between; align-items:center;'>
                    <div>
                      <div style='font-weight:700;font-size:18px'>{row['Name']}</div>
                      <div class='tiny'>{row['Role']} • {row['Company']}</div>
                      <div class='tiny'>{row['Country']} · CRM: {row['CRM'] if row['CRM'] else '—'} · Contact: {row['ContactType']}</div>
                    </div>
                    <div><span class='badge'>{row['Region']}</span></div>
                  </div>
                  <div style='margin-top:8px'>{contact_line}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

with tab_visuals:
    st.subheader("Visuals")
    c1,c2 = st.columns(2)
    with c1:
        by_ct = f["ContactType"].value_counts().reset_index(); by_ct.columns=["Type","Prospects"]
        st.plotly_chart(px.pie(by_ct, names="Type", values="Prospects", title="Contact method split"), use_container_width=True)
    with c2:
        by_crm = f["CRM"].replace({"":"Unknown"}).value_counts().reset_index(); by_crm.columns=["CRM","Prospects"]
        st.plotly_chart(px.pie(by_crm, names="CRM", values="Prospects", title="CRM presence"), use_container_width=True)

    if f["Sector"].replace({"":"(blank)"}).nunique() > 1:
        st.plotly_chart(px.bar(f["Sector"].value_counts().reset_index().rename(columns={"index":"Sector","count":"Prospects"}),
                               x="Sector", y="Prospects", title="Prospects by Sector Focus"), use_container_width=True)

    by_company = f.groupby("Company").size().reset_index(name="Prospects").sort_values("Prospects", ascending=False)
    st.plotly_chart(px.treemap(by_company, path=["Company"], values="Prospects", title="Company Treemap"), use_container_width=True)

    if f["Country"].replace({"":"(blank)"}).nunique() > 1:
        geo = f.groupby("Country").size().reset_index(name="Prospects")
        try:
            st.plotly_chart(px.choropleth(geo, locations="Country", locationmode="country names", color="Prospects", title="Prospects by Country"), use_container_width=True)
        except Exception:
            st.info("Some country names are not recognized for mapping.")

    roles = f["Role"].replace({"":"(blank)"}).value_counts().reset_index(); roles.columns=["Role","Prospects"]
    st.plotly_chart(px.bar(roles.head(25), x="Role", y="Prospects", title="Top Roles"), use_container_width=True)

with tab_quality:
    st.subheader("Data quality checks")
    invalid_email = ~std["EmailClean"].astype(bool) & std["Email"].str.contains("@", na=False)
    url_in_email = std["Email"].str.startswith("http", na=False)
    missing_both = (std["ContactType"]=="None")
    dup_name_company = std.assign(_k=(std["Name"].str.lower()+"|"+std["Company"].str.lower()))._k.duplicated(keep=False)

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("URL in Email column", int(url_in_email.sum()))
    c2.metric("Invalid email format", int(invalid_email.sum()))
    c3.metric("No email & no phone", int(missing_both.sum()))
    c4.metric("Duplicate name+company", int(dup_name_company.sum()))

    with st.expander("Rows with URL in Email"):
        st.dataframe(std[url_in_email][["Name","Company","Email","Phone","Country"]], use_container_width=True)
    with st.expander("Rows with no contact method"):
        st.dataframe(std[missing_both][["Name","Company","Email","Phone","Country"]], use_container_width=True)
    with st.expander("Duplicate name+company"):
        st.dataframe(std[dup_name_company][["Name","Company","Email","Phone","Country"]], use_container_width=True)

with tab_tools:
    st.subheader("Export & Lists")
    real_emails = f["EmailClean"][f["HasEmail"]].dropna().unique().tolist()
    phones = f["Phone"][f["HasPhone"]].dropna().unique().tolist()
    st.text_area("Emails (real emails only)", ", ".join(real_emails), height=120)
    st.text_area("Phones", ", ".join(phones), height=120)

    colA,colB = st.columns(2)
    with colA:
        st.download_button("Download filtered CSV", f.drop(columns=["EmailClean","PhoneClean"]).to_csv(index=False).encode("utf-8"),
                           "prospects_filtered.csv", "text/csv")
    with colB:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="xlsxwriter") as wr:
            f.drop(columns=["EmailClean","PhoneClean"]).to_excel(wr, index=False, sheet_name="Prospects")
        st.download_button("Download filtered Excel", buf.getvalue(), "prospects_filtered.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
