import asyncio
import os
import json
from playwright.async_api import async_playwright
import google.generativeai as genai
import getpass

async def main():
    # 보안 강화를 위해 환경변수에서 우선적으로 키를 찾거나 실행 시 직접 입력받습니다.
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("\n💡 팁: OS 환경변수로 'GEMINI_API_KEY'를 등록해두면 매번 칠 필요가 없습니다.")
        api_key = getpass.getpass("Gemini API 키를 입력해주세요 (보안을 위해 화면에 표시되지 않습니다): ")
        if not api_key.strip():
            print("❌ API 키가 입력되지 않아 스크립트를 종료합니다.")
            return

    # Playwright를 이용해 브라우저 실행
    async with async_playwright() as p:
        # headless=True 옵션을 사용하면 백그라운드에서 실행되며 브라우저 창이 뜨지 않습니다.
        # 따로 downloads_path를 지정하지 않으면 임시 파일(UUID 파일)은 OS 임시 폴더에 저장되었다가 종료 시 삭제됩니다.
        browser = await p.chromium.launch(headless=True)
        
        # 다운로드를 허용하는 브라우저 컨텍스트 생성
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        
        # 1. 대상 팝업창 링크로 직접 접속
        url = 'https://info.nec.go.kr/electioninfo/precandidate_detail_info.xhtml?electionId=0020260603&huboId=100153765'
        print(f"1. 해당 팝업 링크 접속 중: {url}")
        
        # 타임아웃을 넉넉히 설정 (선관위 홈페이지 접속이 일시적으로 느릴 수 있음)
        await page.goto(url, timeout=60000)
        
        # --- 기본정보 추출 및 JSON 저장 ---
        print("1-5. 기본정보(테이블) 추출 중...")
        await page.wait_for_selector('table tbody tr', timeout=15000)
        rows = await page.query_selector_all('table tbody tr')
        basic_info = {}
        for row in rows:
            th = await row.query_selector('th')
            td = await row.query_selector('td')
            if th and td:
                key = (await th.inner_text()).strip()
                # 줄바꿈 및 스페이스 정리
                value = (await td.inner_text()).strip()
                basic_info[key] = value
                
        os.makedirs("./downloads", exist_ok=True)
        json_path = "./downloads/basic_info.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(basic_info, f, ensure_ascii=False, indent=4)
        print(f"✅ 기본정보 JSON 저장 완료: {json_path}")
        
        # --- 후보자 사진 다운로드 ---
        photo_img = await page.query_selector('img[alt="예비후보자 사진"]')
        if photo_img:
            photo_src = await photo_img.get_attribute('src')
            if photo_src:
                # 상대 경로일 경우 도메인 추가
                photo_url = f"https://info.nec.go.kr{photo_src}" if photo_src.startswith('/') else photo_src
                print(f"1-6. 후보자 사진 다운로드 중...")
                
                photo_response = await page.request.get(photo_url)
                if photo_response.ok:
                    photo_bytes = await photo_response.body()
                    photo_path = "./downloads/candidate_photo.jpg"
                    with open(photo_path, "wb") as f:
                        f.write(photo_bytes)
                    print(f"✅ 후보자 사진 저장 완료: {photo_path}")
                else:
                    print(f"❌ 사진 다운로드 실패 (상태 코드: {photo_response.status})")
        else:
            print("❌ 후보자 사진 요소를 찾을 수 없습니다.")
        
        # 2. '전과' 탭 렌더링 대기 및 클릭
        await page.wait_for_selector('text="전과"', timeout=15000)
        print("2. '전과' 탭 클릭")
        await page.click('text="전과"')
        
        print("3. 문서 뷰어 로딩 대기 중...")
        # 뷰어(iframe)가 랜더링될 충분한 시간을 부여합니다.
        await asyncio.sleep(4)
        
        # 4. 문서 뷰어 역할을 하는 iframe(Synap Viewr) 찾기
        viewer_frame = None
        for frame in page.frames:
            # Synap 문서 뷰어 프레임 식별
            if "doc.html" in frame.url or "synap" in frame.url.lower():
                viewer_frame = frame
                break
                
        if viewer_frame:
            print(f"4. 뷰어 프레임 감지 완료. 다운로드 버튼 대기 중...")
            
            # 다운로드 버튼(#download-btn)이 로드 될 때까지 대기
            await viewer_frame.wait_for_selector('#download-btn', timeout=15000)
            
            print("5. 원본 PDF 다운로드 시작...")
            
            # 다운로드 이벤트 캡쳐 준비 후 버튼 클릭
            async with page.expect_download() as download_info:
                await viewer_frame.click('#download-btn')
            
            download = await download_info.value
            
            # 저장 경로 생성
            os.makedirs("./downloads", exist_ok=True)
            save_path = f"./downloads/{download.suggested_filename}"
            
            # 다운로드 저장
            await download.save_as(save_path)
            print(f"6. ✅ 다운로드 완료! 저장 위치: {save_path}")
            
            print("7. Gemini 1.5 Flash API를 이용해 PDF 내용 파싱 중...")
            try:
                # 보안을 위해 입력받은 API 키로 설정
                genai.configure(api_key=api_key)
                
                print("  - PDF 파일 업로드 중...")
                # Gemini에 직접 파악 가능한 형태로 파일 업로드
                sample_file = genai.upload_file(path=save_path, mime_type="application/pdf")
                
                # Gemini 1.5 Flash 모델 초기화
                # 응답 형식을 JSON 구조로 완벽히 한정하기 위해 response_mime_type 설정
                model = genai.GenerativeModel(
                    model_name='gemini-flash-latest',
                    generation_config={"response_mime_type": "application/json"}
                )
                
                print("  - 데이터 추출 및 JSON 구조화 요청 중...")
                prompt = "첨부된 문서에서 감지되는 모든 항목과 주요 전과 기록 내용을 논리적인 Key-Value 쌍의 JSON 형식으로 완벽하게 파싱해서 추출해줘."
                
                response = model.generate_content([sample_file, prompt])
                
                # JSON 결과값 저장
                gemini_json_path = "./downloads/gemini_results.json"
                
                # Gemini 응답은 텍스트지만 response_mime_type 지정으로 JSON 형식 문자열임. 
                # 파싱해서 예쁘게(indent=4) 저장합니다.
                parsed_json = json.loads(response.text)
                with open(gemini_json_path, 'w', encoding='utf-8') as f:
                    json.dump(parsed_json, f, ensure_ascii=False, indent=4)
                    
                print(f"8. ✅ 문서 데이터 추출 완료! JSON 파일 저장 위치: {gemini_json_path}")
                
            except Exception as e:
                print(f"❌ Gemini API 처리 중 오류가 발생했습니다: {e}")
            
        else:
            print("❌ 문서 뷰어 iframe을 찾을 수 없습니다. 페이지 구조를 다시 확인해주세요.")
            
        # 모든 작업 완료 후 브라우저 닫기
        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
