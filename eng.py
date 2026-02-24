import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime
import time
import random

# 1. 페이지 설정
st.set_page_config(page_title="영문공시 필터링 도구 (KOSPI/KOSDAQ)", layout="wide")

st.title('🎯 오늘의 영문 번역대상 공시')
st.markdown("---")

# --- 사이드바 공지사항 ---
with st.sidebar:
    st.markdown("## 🚨 중요 공지")
    st.warning(
        """
        **본 사이트는 실시간 데이터를 참조하므로, 트래픽 집중 시 외부 서버로부터 일시적 차단이 발생할 수 있습니다.** 안정적인 서비스 이용을 위해 **총 3개의 사이트**를 운영 중이니, 장애 발생 시 다른 주소로 접속해 보시기 바랍니다.
        
        ---
        **🔗 이용 가능한 사이트 목록**
        1. https://englishkind.streamlit.app/
        2. https://english-kospi.streamlit.app/
        3. https://englishkospi.streamlit.app/
        """
    )
    st.markdown("---")
    
# 2. 데이터 로드 (캐싱 적용, 범용 함수로 변경)
@st.cache_data
def load_reference_data(format_file, company_file):
    try:
        df_svc = pd.read_csv(format_file, dtype=str)
        df_listed = pd.read_csv(company_file, dtype=str)
        if not df_listed.empty and '회사코드' in df_listed.columns:
            # 종목코드를 6자리로 맞춤
            df_listed['회사코드'] = df_listed['회사코드'].astype(str).str.zfill(6) 
        return df_svc, df_listed
    except Exception as e:
        st.error(f"⚠️ {format_file} 또는 {company_file} 불러오는 중 오류 발생: {e}")
        return pd.DataFrame(), pd.DataFrame()

# 코스피/코스닥 각각의 파일 로드
df_kospi_svc, df_kospi_listed = load_reference_data("kospi_format.csv", "kospi_company.csv")
df_kosdaq_svc, df_kosdaq_listed = load_reference_data("kosdaq_format.csv", "kosdaq_company.csv")

# 3. 날짜 설정
selected_date = st.date_input("📅 조회일자 선택", value=datetime.today())
today_str = selected_date.strftime("%Y-%m-%d")

# 4. 크롤링 엔진 (market_type 파라미터 추가)
def get_all_kind_data(date_str, market_type):
    main_url = "https://kind.krx.co.kr/disclosure/todaydisclosure.do"
    ajax_url = "https://kind.krx.co.kr/disclosure/todaydisclosure.do"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Referer": main_url,
        "X-Requested-With": "XMLHttpRequest"
    }

    session = requests.Session()
    all_rows = []
    
    try:
        session.get(main_url, headers=headers)
        
        payload = {
            "method": "searchTodayDisclosureSub",
            "currentPageSize": 100,
            "pageIndex": 1,
            "orderMode": "0", 
            "orderStat": "A", 
            "forward": "todaydisclosure_sub",
            "marketType": market_type, # 1: 코스피, 2: 코스닥
            "selDate": date_str
        }
        
        first_resp = session.post(ajax_url, data=payload, headers=headers)
        soup = BeautifulSoup(first_resp.text, 'html.parser')
        
        info_text = soup.select_one('.info.type-00')
        total_pages = 1
        if info_text:
            page_match = re.search(r'/(\d+)', info_text.text)
            if page_match:
                total_pages = int(page_match.group(1))
        
        progress_text = st.empty()
        progress_bar = st.progress(0)

        for page in range(1, total_pages + 1):
            progress_text.text(f"⏳ {total_pages}페이지 중 {page}페이지 수집 중...")
            payload["pageIndex"] = page
            resp = session.post(ajax_url, data=payload, headers=headers)
            p_soup = BeautifulSoup(resp.text, 'html.parser')
            
            table = p_soup.find('table', class_='list type-00 mt10')
            if not table: continue
            
            rows = table.find('tbody').find_all('tr')
            for tr in rows:
                tds = tr.find_all('td')
                if len(tds) < 5 or "결과가 없습니다" in tr.text: continue
                
                comp_a = tds[1].find('a')
                comp_code = ""
                if comp_a and comp_a.has_attr('onclick'):
                    code_match = re.search(r"companysummary_open\('(\d+)'\)", comp_a['onclick'])
                    if code_match: comp_code = code_match.group(1).zfill(6)
                
                title_a = tds[2].find('a')
                title = title_a.get('title', '').strip() if title_a else tds[2].text.strip()
                acpt_no = ""
                if title_a and title_a.has_attr('onclick'):
                    no_match = re.search(r"openDisclsViewer\('(\d+)'", title_a['onclick'])
                    if no_match: acpt_no = no_match.group(1)
                
                all_rows.append({
                    '시간': tds[0].text.strip(),
                    '회사코드': comp_code,
                    '회사명': tds[1].text.strip(),
                    '공시제목': title,
                    '제출인': tds[3].text.strip(),
                    '상세URL': f"https://kind.krx.co.kr/common/disclsviewer.do?method=search&acptno={acpt_no}" if acpt_no else ""
                })
            
            progress_bar.progress(page / total_pages)
            time.sleep(random.uniform(0.3, 0.6))
            
        progress_text.empty()
        progress_bar.empty() # 작업 완료 후 진행바 숨김
        return pd.DataFrame(all_rows)

    except Exception as e:
        st.error(f"❌ 데이터 수집 중 오류: {e}")
        return pd.DataFrame()

# 5. 실행 및 필터링 핵심 로직 (재사용 가능한 함수)
def process_and_display(market_name, market_type, df_format, df_company, target_date):
    if df_format.empty or df_company.empty:
        st.warning(f"⚠️ {market_name} 기준 데이터(CSV)가 로드되지 않았습니다.")
        return

    with st.spinner(f'{target_date} [{market_name}] 전체 공시를 전수 조사 중입니다...'):
        df_raw = get_all_kind_data(target_date, market_type)
        
        if not df_raw.empty:
            target_forms = df_format['서식명'].unique().tolist()
            target_codes = df_company['회사코드'].tolist()

            def filter_logic(row):
                title = row['공시제목']
                code = row['회사코드']
                if title.startswith(("추가상장", "변경상장")): return False
                return any(f in title for f in target_forms) and (code in target_codes)

            final_df = df_raw[df_raw.apply(filter_logic, axis=1)]

            st.subheader(f"📊 {target_date} [{market_name}] 전체 공시 {len(df_raw)}건 중 필터링 결과")
            if not final_df.empty:
                final_df = final_df.sort_values(by='시간')
                st.dataframe(
                    final_df[['시간', '회사명', '공시제목', '제출인', '상세URL']],
                    column_config={"상세URL": st.column_config.LinkColumn("공시보기")},
                    hide_index=True, use_container_width=True
                )
            else:
                st.info("해당 날짜에 조건에 맞는 공시가 없습니다.")
        else:
            st.warning("데이터를 가져오지 못했습니다. 장 시작 전이거나 접근이 일시적으로 차단되었을 수 있습니다.")

# 6. 화면 출력 (버튼 배치)
st.markdown("### 🔍 조회할 시장을 선택하세요")

# 버튼들을 한 줄에 나란히 배치 (원하시면 위아래 배치로 변경 가능)
col1, col2 = st.columns(2)

with col1:
    if st.button('🚀 코스피 영문공시 지원대상 조회', use_container_width=True):
        process_and_display("코스피", "1", df_kospi_svc, df_kospi_listed, today_str)

with col2:
    if st.button('🚀 코스닥 영문공시 지원대상 조회', use_container_width=True):
        process_and_display("코스닥", "2", df_kosdaq_svc, df_kosdaq_listed, today_str)
