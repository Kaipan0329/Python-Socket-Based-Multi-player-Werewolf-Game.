#Client
import socket
import threading
import json
import os
import time
import platform

remote_addr = ('127.0.0.1', 6000)
use_emoji = platform.system() != 'Windows'

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

try:
    sock.connect(remote_addr)
except ConnectionRefusedError:
    print("無法連線到伺服器！")
    os._exit(0)

f = sock.makefile(encoding='utf-8')
room_name = None

# ------------------ 登入暱稱 ------------------
while True:
    nickname = input("📥 請輸入你的暱稱/別名：")
    msgdict = {"type": 1, "nickname": nickname}
    sock.sendall((json.dumps(msgdict)+'\n').encode('utf-8'))

    try:
        text = f.readline()
        msgdict = json.loads(text)
        if msgdict.get('type') == 2:
            if 'error' in msgdict:
                print(f"❌ {msgdict['error']}")
                continue
            print("✅ 成功進入伺服器！")
            break
        else:
            print("❌ 進入伺服器失敗！")
            os._exit(0)
    except:
        print("伺服器斷線")
        sock.close()
        os._exit(0)

# ------------------ 使用說明 ------------------\
print("\n==================== 使用說明 ====================")
print(" 1️⃣ 　創建房間：　　　　　　　　　　輸入 /create")
print(" 2️⃣ 　加入房間：　　　　　　　　　　輸入 /join")
print(" 3️⃣ 　查看房間成員：　　　　　　　　輸入 /who")
print(" 4️⃣ 　離開房間：　　　　　　　　　　輸入 /leave")
print(" 5️⃣ 　開始遊戲（host 才可）：　　　 輸入 /start")
print(" 6️⃣ 　指令集查詢：　　　　　　　　　輸入 /help")
print("==================== 遊戲指令 ====================")
print(" ⭐  直接輸入不需要斜線 ❗")
print(" 1️⃣ 　白天投票：　　　　　　　　　　輸入 投票 <名>")
print(" 2️⃣ 　狼人/狼王： 　　　　　　　　　輸入 殺 <名>")
print(" 3️⃣ 　狼王(白天)：　　　　　　　　　輸入 報復 <名>")
print(" 4️⃣ 　預言家：　　　　　　　　　　　輸入 查驗 <名>")
print(" 5️⃣ 　守衛：　　　　　　　　　　　　輸入 守護 <名>")
print(" 6️⃣ 　女巫使用毒藥：　　　　　　　　輸入 毒藥 <名>")
print(" 7️⃣ 　女巫使用解藥：　　　　　　　　輸入 解藥 <名>")
print(" 8️⃣ 　女巫不使用藥水：　　　　　　　輸入 不使用")
print(" 9️⃣ 　獵人：　　　　　　　　　　　　輸入 開槍 <名>")
print("===================================================")
print(" 💡  小提示：房間內直接輸入文字即可聊天 ")
print("\n===================================================")

# ------------------ 發送訊息 ------------------
def send_message():
    global room_name
    while True:
        try:
            msg = input()
            if msg.strip() == '':
                continue

            # 創建房間
            if msg.lower() == '/create':
                if room_name:
                    print("❗ 你已在房間中，請先離開原房間")
                    continue
                rn = input("請輸入房間名稱：")
                rp = input("請輸入房間密碼：")
                msgdict = {"type":3,"nickname":nickname,"message":f"/create {rn} {rp}"}

            # 加入房間
            elif msg.lower() == '/join':
                if room_name:
                    print("❗ 你已在房間中，請先離開原房間")
                    continue
                rn = input("請輸入房間名稱：")
                rp = input("請輸入房間密碼：")
                msgdict = {"type":3,"nickname":nickname,"message":f"/join {rn} {rp}"}

            # 離開房間
            elif msg.lower() == '/leave':
                msgdict = {"type":3,"nickname":nickname,"message":"/leave"}
                sock.sendall((json.dumps(msgdict)+'\n').encode())
                room_name = None
                print("✅ 你已離開房間")
                continue

            # 其他聊天或指令
            else:
                msgdict = {"type":3,"nickname":nickname,"message":msg}

            sock.sendall((json.dumps(msgdict)+'\n').encode())

        except (ConnectionResetError,BrokenPipeError):
            print("⚠ 伺服器斷線")
            break

# ------------------ 接收訊息 ------------------
def recv_message():
    global room_name
    while True:
        try:
            text = f.readline()
            if text == '':
                print("⚠ 伺服器已斷線")
                break
            msgdict = json.loads(text)
            ts = time.strftime("%H:%M:%S")
            if msgdict['type'] == 3:
                print(f"[{ts}] [{msgdict['nickname']}]：{msgdict['message']}")
                # 自動更新 room_name
                if msgdict['nickname'] == '系統':
                    if '加入房間' in msgdict['message']:
                        room_name = msgdict['message'].split()[0].replace('房間','')
                    elif '離開房間' in msgdict['message']:
                        room_name = None
        except:
            continue

# ------------------ 啟動執行緒 ------------------
threading.Thread(target=send_message, daemon=True).start()
threading.Thread(target=recv_message, daemon=True).start()

while True:
    time.sleep(1)
