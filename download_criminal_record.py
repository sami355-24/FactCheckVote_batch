import asyncio
import os
import json
from playwright.async_api import async_playwright

async def main():
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
            
        else:
            print("❌ 문서 뷰어 iframe을 찾을 수 없습니다. 페이지 구조를 다시 확인해주세요.")
            
        # 모든 작업 완료 후 브라우저 닫기
        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
