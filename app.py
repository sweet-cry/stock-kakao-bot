from flask import Flask, request, jsonify
import subprocess
import threading
import schedule
import time
import requests
import os
from datetime import datetime

app = Flask(__name__)

KAKAO_REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY", "")

def send_kakao_message(user_key, text):
    """카카오 사용자에게 메시지 전송"""
    try:
        headers = {
            "Authorization": f"KakaoAK {KAKAO_REST_API_KEY}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        # 너무 길면 자르기 (카톡 최대 1000자)
        if len(text) > 900:
            text = text[:900] + "\n\n...(요약 완료)"
        data = {
            "receiver_uuids": f'["{user_key}"]',
            "template_object": f'{{"object_type":"text","text":"{text}","link":{{"web_url":"https://stock-kakao-bot-production.up.railway.app"}}}}'
        }
        requests.post(
            "https://kapi.kakao.com/v1/api/talk/friends/message/send",
            headers=headers, data=data, timeout=10
        )
    except Exception as e:
        print(f"카카오 메시지 전송 실패: {e}")

def run_claude(command):
    """Claude Code CLI 실행 후 결과 반환"""
    try:
        result = subprocess.run(
            ["claude", "-p", command],
            capture_output=True, text=True, timeout=300,
            encoding="utf-8"
        )
        output = result.stdout.strip()
        if len(output) > 900:
            output = output[:900] + "\n\n...(요약 완료)"
        return output if output else "분석 결과를 가져오지 못했습니다."
    except subprocess.TimeoutExpired:
        return "⏱ 분석 시간 초과 (5분). 다시 시도해주세요."
    except Exception as e:
        return f"오류 발생: {str(e)}"

def parse_command(text):
    """카톡 메시지 파싱 → Claude 커맨드 변환"""
    text = text.strip()

    # 실적 분석
    if "실적" in text:
        ticker = text.replace("실적", "").strip().upper() or "LCID"
        return f"/equity-research:earnings {ticker} Q4", f"📊 {ticker} 실적 분석 중..."

    # 유사기업 분석
    elif "comps" in text.lower() or "유사기업" in text or "비교" in text:
        ticker = text.replace("comps", "").replace("유사기업", "").replace("비교", "").strip().upper() or "LCID"
        return f"/financial-analysis:comps {ticker}", f"🔍 {ticker} 유사기업 분석 중..."

    # DCF 밸류에이션
    elif "dcf" in text.lower() or "밸류" in text or "목표주가" in text:
        ticker = text.replace("dcf", "").replace("밸류", "").replace("목표주가", "").strip().upper() or "LCID"
        return f"/financial-analysis:dcf {ticker}", f"💰 {ticker} DCF 밸류에이션 중..."

    # 시장 브리핑
    elif "브리핑" in text or "시장" in text:
        return "오늘 미국 주식시장 주요 이슈와 섹터별 동향을 한국어로 간략히 브리핑해줘", "🌎 시장 브리핑 준비 중..."

    # 도움말
    elif "도움말" in text or "help" in text.lower():
        return None, """📌 사용 가능한 명령어:
• [티커] 실적 → 실적 분석 (예: LCID 실적)
• [티커] 유사기업 → Comps 분석 (예: TSLA 유사기업)
• [티커] 밸류 → DCF 목표주가 (예: LCID 밸류)
• 시장 브리핑 → 오늘 시장 요약"""

    else:
        return None, "❓ 명령어를 인식하지 못했습니다.\n'도움말'을 입력하세요."

@app.route("/kakao", methods=["POST"])
def kakao_webhook():
    """카카오 오픈빌더 웹훅 수신"""
    data = request.get_json()

    try:
        user_text = data["userRequest"]["utterance"]
        user_key = data["userRequest"]["user"]["properties"].get("plusfriendUserKey", "")
    except (KeyError, TypeError):
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": "오류가 발생했습니다."}}]}})

    command, loading_msg = parse_command(user_text)

    if command is None:
        response_text = loading_msg
    else:
        # 백그라운드에서 Claude 실행 → 완료 후 카톡으로 결과 전송
        def run_and_respond():
            result = run_claude(command)
            send_kakao_message(user_key, result)

        thread = threading.Thread(target=run_and_respond)
        thread.start()
        response_text = f"{loading_msg}\n\n✅ 분석을 시작했습니다. 완료되면 이 채팅으로 결과를 전송합니다.\n예상 소요시간: 2~5분"

    return jsonify({
        "version": "2.0",
        "template": {
            "outputs": [
                {"simpleText": {"text": response_text}}
            ]
        }
    })

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})

# ── 매일 아침 시장 브리핑 스케줄러 ──────────────────────
def morning_briefing():
    """매일 오전 8시 (KST) 시장 브리핑 자동 실행"""
    print(f"[{datetime.now()}] 시장 브리핑 시작...")
    result = run_claude("오늘 미국 주식시장 주요 이슈, 섹터별 동향, 주목할 종목을 한국어로 브리핑해줘")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    report_dir = r"C:\Users\ssk13\OneDrive\Desktop\Reports"
    os.makedirs(report_dir, exist_ok=True)
    with open(f"{report_dir}\\briefing_{timestamp}.txt", "w", encoding="utf-8") as f:
        f.write(result)
    print(f"[{datetime.now()}] 브리핑 저장 완료")

def run_scheduler():
    schedule.every().day.at("08:00").do(morning_briefing)
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    # 스케줄러 백그라운드 실행
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
