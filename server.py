# server.py
import socket
import threading
import json
import time
import platform
import random
from collections import Counter

BUFFER_SIZE = 4096
bind_ip = '0.0.0.0'
bind_port = 6000

client_list = [] 
rooms = {} 
MAX_PLAYERS = 12 # 房間人數上限

use_emoji = platform.system() != 'Windows'

def json_msg(sender, msg_text):
    return (json.dumps({"type": 3, "nickname": sender, "message": msg_text}) + '\n').encode('utf-8')

# 同陣營訊息
def send_private_msg(client_socket, sender, msg_text):
    data = json_msg(sender, msg_text)
    try:
        client_socket.sendall(data)
    except:
        pass

# 輔助函數：取得房間內存活玩家名單字串
def get_alive_list_str(room_name, exclude_list=None):
    if room_name not in rooms: return ""
    if exclude_list is None: exclude_list = []
    
    alive_names = [
        m['nickname'] 
        for m in rooms[room_name]['members'] 
        if m.get('alive') and m['nickname'] not in exclude_list
    ]
    return ", ".join(alive_names)

# 廣播訊息給房間內所有死亡成員 (鬼魂聊天)
def broadcast_ghost_room(room_name, sender, msg_text):
    if room_name not in rooms: return
    data = json_msg(sender, f"(鬼魂) {msg_text}")
    for c in rooms[room_name]['members'][:]:
        if not c.get('alive'):
            try: c['socket'].sendall(data)
            except: pass

# 廣播訊息給房間內所有成員
def broadcast_room(room_name, sender, msg_text):
    if room_name not in rooms: return
    data = json_msg(sender, msg_text)
    for c in rooms[room_name]['members'][:]:
        # 判斷是否顯示訊息
        is_game_message = (sender == "系統" or rooms[room_name].get('state') != 'playing' or rooms[room_name].get('game',{}).get('phase') == 'day')
        
        # 狼人夜間交流
        if rooms[room_name].get('state') == 'playing' and rooms[room_name].get('game',{}).get('phase') == 'wolf' and c.get('alive') and c.get('game_role') in ['狼人', '狼王']:
            is_wolf_chat = c.get('game_role') in ['狼人', '狼王']
            sender_is_wolf = any(m['nickname'] == sender and m['game_role'] in ['狼人', '狼王'] for m in rooms[room_name]['members'])
            if not is_game_message and is_wolf_chat and sender_is_wolf:
                try: c['socket'].sendall(data)
                except: pass
                continue 
            
        if is_game_message:
            try: c['socket'].sendall(data)
            except:
                print(f"[{time.strftime('%H:%M:%S')}] ⚠ 移除無法連線的 {c.get('nickname','?')}")
                try:
                    rooms[room_name]['members'].remove(c)
                    if c in client_list: client_list.remove(c)
                except: pass
        elif rooms[room_name].get('state') == 'playing':
             # 夜間普通玩家聊天 (自言自語)
             if c['nickname'] == sender:
                 send_private_msg(c['socket'], "系統", f"(只有你看得到) 你說：{msg_text}")

# 離開房間函數
def leave_room(nickname, room_name):
    if room_name not in rooms: return None
    if rooms[room_name].get('game',{}).get('revenge_target') == nickname:
        rooms[room_name]['game']['revenge_target'] = None

    rooms[room_name]['members'] = [c for c in rooms[room_name]['members'] if c['nickname'] != nickname]
    broadcast_room(room_name, "系統", f"{nickname} 離開房間")

    if rooms[room_name]['host'] == nickname:
        if rooms[room_name]['members']:
            new_host_member = rooms[room_name]['members'][0]
            new_host_name = new_host_member['nickname']
            rooms[room_name]['host'] = new_host_name
            new_host_member['role'] = 'host'
            broadcast_room(room_name, "系統", f"房主已轉移給 {new_host_name}")
        else:
            try: del rooms[room_name]
            except: pass

    for c in client_list:
        if c['nickname'] == nickname:
            c['room'] = None; c['role'] = 'user'
            c.pop('game_role', None); c.pop('alive', None); c.pop('is_idiot', None)
    return None

# 檢查目標是否存在且存活
def check_alive_target(room_name, target_name):
    if room_name not in rooms: return False
    return any(c['nickname'] == target_name and c.get('alive') for c in rooms[room_name]['members'])

# 檢查遊戲勝負
def check_game_over(room_name):
    if room_name not in rooms: return True
    members = rooms[room_name]['members']
    alive_wolves = [c for c in members if c.get('game_role') in ['狼人', '狼王'] and c.get('alive')]
    alive_humans = [c for c in members if c.get('game_role') not in ['狼人', '狼王'] and c.get('alive')]

    if not alive_wolves:
        broadcast_room(room_name, "系統", "遊戲結束：狼人陣營全滅，好人陣營獲勝！")
        return True 
    if len(alive_wolves) >= len(alive_humans):
        broadcast_room(room_name, "系統", "遊戲結束：狼人陣營數量等於或大於好人陣營，狼人陣營獲勝！")
        return True 
    return False

# 分配狼人殺角色
def assign_roles(room_name):
    members = rooms[room_name]['members']
    num_players = len(members)
    roles_pool = []

    if num_players < 4 or num_players > MAX_PLAYERS: 
         broadcast_room(room_name, "系統", f"玩家人數 {num_players} 不符合 4~{MAX_PLAYERS} 人要求，遊戲取消。")
         rooms[room_name]['state'] = 'waiting'
         return

    roles_pool.extend(['預言家', '女巫'])
    if num_players >= 6: roles_pool.append('獵人')
    if num_players >= 5: roles_pool.append('守衛')
    if num_players >= 8: roles_pool.append('白癡')

    num_wolves = 0
    num_wolf_king = 0
    if num_players <= 5: num_wolves = 1
    elif num_players in [6, 7]: num_wolves = 2
    elif num_players in [8, 9]: num_wolves = 2
    elif num_players in [10, 11]: num_wolves = 2; num_wolf_king = 1
    elif num_players == 12: num_wolves = 3; num_wolf_king = 1
        
    roles_pool.extend(['狼人'] * num_wolves)
    roles_pool.extend(['狼王'] * num_wolf_king)

    while len(roles_pool) < num_players: roles_pool.append('村民')

    random.shuffle(roles_pool)
    for i, c in enumerate(members):
        c['game_role'] = roles_pool[i]
        c['alive'] = True
        c['is_idiot'] = False
        c.pop('can_use_potion', None)
        c.pop('can_use_poison', None)

        if c['game_role'] == '女巫':
             c['can_use_potion'] = True
             c['can_use_poison'] = True

        try:
            msg = f"======== 遊戲開始 ========\n您分配到的職業是：【**{c['game_role']}**】"
            if c['game_role'] in ['狼人', '狼王']:
                wolf_mates = [m['nickname'] for m in members if m['game_role'] in ['狼人', '狼王'] and m['nickname'] != c['nickname']]
                if wolf_mates: msg += f"\n您的隊友是：{', '.join(wolf_mates)}"
            send_private_msg(c['socket'], "系統", msg)
        except: continue
            
    broadcast_room(room_name, "系統", f"角色已分配完畢，共 {num_players} 人，準備進入第一夜。")

# 等待機制
def wait_for_action(room_name, role, timeout=60):
    start = time.time()
    countdown_sent = {5: False, 4: False, 3: False, 2: False, 1: False}
    
    while time.time() - start < timeout:
        if room_name not in rooms: return True
        game = rooms[room_name].get('game', {})
        members = rooms[room_name]['members']
        time_remaining = int(timeout - (time.time() - start))

        if 1 <= time_remaining <= 5 and not countdown_sent[time_remaining]:
            broadcast_room(room_name, "系統", f"**請注意！** 剩餘 {time_remaining} 秒！")
            countdown_sent[time_remaining] = True
            
        if role == "wolf":
            wolves = [c['nickname'] for c in members if c.get('game_role') in ['狼人','狼王'] and c.get('alive')]
            if not wolves: return True
            votes = game.get('wolves_votes', {})
            if all(w in votes for w in wolves): return True
        
        elif role == "guard":
            if game.get('guard_target') is not None: return True
            if not any(c.get('game_role') == '守衛' and c.get('alive') for c in members): return True
        
        elif role == "seer":
            if game.get('seer_target') is not None: return True
            if not any(c.get('game_role') == '預言家' and c.get('alive') for c in members): return True

        elif role == "witch":
            if game.get('witch_action') is not None: return True
            if not any(c.get('game_role') == '女巫' and c.get('alive') for c in members): return True

        elif role == "day_vote":
            alive_players = [c['nickname'] for c in members if c.get('alive') and not c.get('is_idiot')] 
            votes = game.get('day_votes', {})
            if all(p in votes for p in alive_players): return True

        time.sleep(0.1)
    
    if room_name in rooms:
        broadcast_room(room_name, "系統", "**時間到！** 行動結束。")
    return False

# 遊戲主流程
def start_werewolf_game(room_name):
    day_count = 1
    game_running = True

    while game_running:
        if room_name not in rooms: break
        
        broadcast_room(room_name, "系統", f"\n=========== 第 {day_count} 夜 ===========")
        time.sleep(1)

        # --- 1. 夜晚初始化 ---
        with rooms[room_name]['lock']:
            broadcast_room(room_name, "系統", "夜晚降臨，所有玩家請閉眼")
            last_guard_target = rooms[room_name]['game'].get('guard_target', '無')
            rooms[room_name]['game'] = {
                "phase": None, "witch_action": None, "wolves_votes": {},
                "seer_target": None, "guard_target": None,
                "last_guard_target": last_guard_target, "day_votes": {},
                "revenge_target": None
            }
        time.sleep(1)

        # --- 2. 狼人階段 ---
        rooms[room_name]['game']['phase'] = 'wolf'
        wolf_members = [c for c in rooms[room_name]['members'] if c.get('game_role') in ['狼人', '狼王'] and c.get('alive')]
        if wolf_members:
            broadcast_room(room_name, "系統", "狼人請睜眼") 
            
            # 取得可以殺的目標 (排除狼人隊友)
            all_wolves_names = [m['nickname'] for m in rooms[room_name]['members'] if m['game_role'] in ['狼人', '狼王']]
            target_list_str = get_alive_list_str(room_name, exclude_list=all_wolves_names)

            for c in wolf_members:
                msg = (f"獵殺時刻！\n"
                       f"可選擇目標：{target_list_str}\n"
                       f"指令：殺 <玩家名>")
                send_private_msg(c['socket'], "系統", msg)
            
            wait_for_action(room_name, 'wolf', timeout=90) 
            broadcast_room(room_name, "系統", "狼人請閉眼") 

        # --- 3. 計算狼人目標 ---
        game = rooms[room_name]['game']
        wolf_votes = game.get('wolves_votes', {})
        wolf_target = None
        if wolf_votes:
            tally = Counter(wolf_votes.values())
            # 檢查是否有同票，如果沒有，選擇票數最高的
            if tally:
                 max_votes = max(tally.values())
                 candidates = [name for name, count in tally.items() if count == max_votes]
                 if len(candidates) == 1:
                     wolf_target = candidates[0]
                 else: # 平票則視為無效或隨機，此處取最常見的，因為前面已經有處理同票
                      wolf_target = tally.most_common(1)[0][0]

        # --- 4. 守衛階段 ---
        rooms[room_name]['game']['phase'] = 'guard'
        guard_members = [c for c in rooms[room_name]['members'] if c.get('game_role') == '守衛' and c.get('alive')]
        if guard_members:
            broadcast_room(room_name, "系統", "守衛請睜眼")
            target_list_str = get_alive_list_str(room_name)
            for c in guard_members:
                last_target = rooms[room_name]['game'].get('last_guard_target', '無')
                msg = (f"🛡️ 請選擇守護目標 (上次守護: {last_target})\n"
                       f"可選擇目標：{target_list_str}\n"
                       f"指令：守護 <玩家名>")
                send_private_msg(c['socket'], "系統", msg)
            wait_for_action(room_name, 'guard', timeout=60)
            broadcast_room(room_name, "系統", "守衛請閉眼")
            game = rooms[room_name]['game']

        # --- 5. 預言家階段 ---
        rooms[room_name]['game']['phase'] = 'seer'
        seer_members = [c for c in rooms[room_name]['members'] if c.get('game_role') == '預言家' and c.get('alive')]
        if seer_members:
            broadcast_room(room_name, "系統", "預言家請睜眼")
            target_list_str = get_alive_list_str(room_name)
            for c in seer_members:
                msg = (f"請選擇查驗目標\n"
                       f"可選擇目標：{target_list_str}\n"
                       f"指令：查驗 <玩家名>")
                send_private_msg(c['socket'], "系統", msg)
            wait_for_action(room_name, 'seer', timeout=60)
            broadcast_room(room_name, "系統", "預言家請閉眼") 

            if game.get('seer_target'):
                target_name = game['seer_target']
                target_obj = next((m for m in rooms[room_name]['members'] if m['nickname'] == target_name), None)
                if target_obj: # 確保目標還在房間內
                     is_wolf_camp = target_obj['game_role'] in ['狼人', '狼王']
                     result = "是狼人陣營" if is_wolf_camp else "是好人陣營"
                     for c in seer_members:
                         send_private_msg(c['socket'], "系統", f"查驗結果：{target_name} {result}")

        # --- 6. 女巫階段 ---
        rooms[room_name]['game']['phase'] = 'witch'
        witch_member = next((c for c in rooms[room_name]['members'] if c.get('game_role') == '女巫' and c.get('alive')), None)
        if witch_member:
            broadcast_room(room_name, "系統", "女巫請睜眼") 
            wolf_info = f"本晚狼人欲殺害：**{wolf_target}**。" if wolf_target else "本晚狼人沒有指定目標。"
            potion_status = f"解藥: {'有' if witch_member.get('can_use_potion') else '無'}"
            poison_status = f"毒藥: {'有' if witch_member.get('can_use_poison') else '無'}"
            target_list_str = get_alive_list_str(room_name)
            
            msg = (
                f"請選擇操作\n"
                f"==========\n"
                f"{wolf_info}\n"
                f"{potion_status} | {poison_status}\n"
                f"存活名單：{target_list_str}\n"
                f"==========\n"
                f"指令：毒藥 <玩家名> / 解藥 <玩家名> / 不使用" # 修正指令提示
            )
            send_private_msg(witch_member['socket'], "系統", msg)
            wait_for_action(room_name, 'witch', timeout=60)
            broadcast_room(room_name, "系統", "女巫請閉眼")

        # --- 7. 夜晚結算 ---
        witch_action = game.get('witch_action')
        guard_target = game.get('guard_target')
        deaths = []
        is_saved = False 

        if wolf_target:
            if guard_target == wolf_target:
                broadcast_room(room_name, "系統", f"（{wolf_target} 昨晚被守衛保護）")
                wolf_target = None
            elif witch_action and witch_action['type'] == 'save' and witch_action['target'] == wolf_target and witch_member and witch_member.get('can_use_potion'):
                broadcast_room(room_name, "系統", "（女巫使用了解藥）")
                witch_member['can_use_potion'] = False
                wolf_target = None
                is_saved = True
            
            if wolf_target: deaths.append(wolf_target)
        
        if witch_action and witch_action['type'] == 'poison' and witch_member and witch_member.get('can_use_poison'):
            p_target = witch_action['target']
            if p_target:
                 if p_target != guard_target: 
                    deaths.append(p_target)
                    broadcast_room(room_name, "系統", "（女巫使用了毒藥）")
                    witch_member['can_use_poison'] = False
                 else:
                    broadcast_room(room_name, "系統", f"（女巫毒藥目標 {p_target} 被守衛保護，毒藥無效）")

        death_list = []
        # 使用 set 來避免重複死亡
        unique_deaths = list(set(deaths)) 
        for d_name in unique_deaths:
            for c in rooms[room_name]['members']:
                if c['nickname'] == d_name and c.get('alive'):
                    c['alive'] = False
                    death_list.append(d_name)
                    if c.get('game_role') == '狼王':
                        broadcast_room(room_name, "系統", f"狼王 {d_name} 死亡！ (夜晚死亡無法報復)") 
                    if c.get('game_role') == '獵人':
                        broadcast_room(room_name, "系統", f"獵人 {d_name} 死亡！請獵人開槍。") 

        time.sleep(1)
        if death_list: broadcast_room(room_name, "系統", f"天亮了，昨晚死亡的是：{', '.join(death_list)}")
        else: broadcast_room(room_name, "系統", "天亮了，昨晚是平安夜！")

        if check_game_over(room_name):
            rooms[room_name]['state'] = 'waiting'; break

        # --- 8. 白天發言與投票 ---
        rooms[room_name]['game']['phase'] = 'day'
        alive_list_str = get_alive_list_str(room_name)
        broadcast_room(room_name, "系統", f"存活玩家：{alive_list_str}")
        broadcast_room(room_name, "系統", "請討論並投票。指令：`投票 <玩家名>` 或 `投票 棄票`")
        
        wait_for_action(room_name, 'day_vote', timeout=120)

        # 投票結算
        day_votes = rooms[room_name]['game'].get('day_votes', {})
        broadcast_room(room_name, "系統", "投票結束，正在計票...")
        time.sleep(1)
        
        detail_msg = [f"{v} 投給了 {t}" for v, t in day_votes.items()]
        if detail_msg: broadcast_room(room_name, "系統", "\n".join(detail_msg))

        valid_targets = [t for v, t in day_votes.items() if t != '棄票']
        executed = None
        
        if not valid_targets:
            broadcast_room(room_name, "系統", "無人被投票，平安日。")
        else:
            tally = Counter(valid_targets)
            max_votes = max(tally.values())
            candidates = [name for name, count in tally.items() if count == max_votes]

            if len(candidates) > 1:
                broadcast_room(room_name, "系統", f"平票 ({', '.join(candidates)})，無人被處決。")
            else:
                executed = candidates[0]
                target_member = next((m for m in rooms[room_name]['members'] if m['nickname'] == executed), None)
                
                if target_member and target_member.get('game_role') == '白癡':
                    target_member['alive'] = True
                    target_member['is_idiot'] = True
                    broadcast_room(room_name, "系統", f"**{executed}** 是白癡，亮牌！免於處決，但從此不能投票。")
                    executed = None
                else:
                    broadcast_room(room_name, "系統", f"經過多數決投票，**{executed}** 被處決了。")
                    if target_member:
                        target_member['alive'] = False
                        
                        # 狼王報復
                        if target_member.get('game_role') == '狼王':
                            broadcast_room(room_name, "系統", f"狼王 {executed} 死亡！請狼王開槍帶走一人。") 
                            rooms[room_name]['game']['phase'] = 'wolfking_revenge'
                            rooms[room_name]['game']['wolfking_name'] = executed
                            target_list_str = get_alive_list_str(room_name)
                            send_private_msg(target_member['socket'], "系統", f"狼王報復！\n可選目標：{target_list_str}\n指令：報復 <玩家名>")
                            
                            revenge_start = time.time()
                            while time.time() - revenge_start < 10:
                                if rooms[room_name]['game'].get('revenge_target'): break
                                time.sleep(0.5)
                            
                            rooms[room_name]['game']['phase'] = 'day'
                            revenge_target = rooms[room_name]['game'].get('revenge_target')
                            
                            if revenge_target:
                                broadcast_room(room_name, "系統", f"狼王 {executed} 開槍，帶走了 **{revenge_target}**！")
                                revenge_member = next((m for m in rooms[room_name]['members'] if m['nickname'] == revenge_target), None)
                                if revenge_member: revenge_member['alive'] = False
                                    
                        # 獵人報復
                        elif target_member.get('game_role') == '獵人':
                            broadcast_room(room_name, "系統", f"獵人 {executed} 死亡！請獵人開槍。")
                            rooms[room_name]['game']['phase'] = 'hunter_revenge'
                            rooms[room_name]['game']['hunter_name'] = executed
                            target_list_str = get_alive_list_str(room_name)
                            send_private_msg(target_member['socket'], "系統", f"獵人開槍！\n可選目標：{target_list_str}\n指令：開槍 <玩家名> 或 開槍 棄槍")
                            
                            rooms[room_name]['game']['revenge_target'] = None
                            revenge_start = time.time()
                            while time.time() - revenge_start < 10:
                                if rooms[room_name]['game'].get('revenge_target'): break
                                time.sleep(0.5)
                            
                            rooms[room_name]['game']['phase'] = 'day'
                            revenge_target = rooms[room_name]['game'].get('revenge_target')
                            
                            if revenge_target and revenge_target != '棄槍':
                                broadcast_room(room_name, "系統", f"獵人 {executed} 開槍，帶走了 **{revenge_target}**！")
                                revenge_member = next((m for m in rooms[room_name]['members'] if m['nickname'] == revenge_target), None)
                                if revenge_member: revenge_member['alive'] = False
                            elif revenge_target == '棄槍':
                                broadcast_room(room_name, "系統", "獵人選擇了棄槍。")
                        
        if check_game_over(room_name):
            rooms[room_name]['state'] = 'waiting'; break

        day_count += 1
        broadcast_room(room_name, "系統", "即將進入下一夜...")
        time.sleep(3)

# 客戶端 Thread
def client_thread(sock, addr):
    global client_list, rooms
    nickname = None; room_name = None
    f = sock.makefile(encoding='utf-8')

    while True:
        try:
            text = f.readline()
            if not text: break
            message = json.loads(text)

            if message['type'] == 1:
                nickname_try = message['nickname']
                if any(c['nickname'] == nickname_try for c in client_list):
                    sock.sendall((json.dumps({"type":2, "error":"暱稱重複"})+'\n').encode('utf-8')); continue
                nickname = nickname_try
                client_list.append({'nickname': nickname, 'socket': sock, 'room': None, 'role': 'user'})
                print(f"[{time.strftime('%H:%M:%S')}]  {nickname} 加入伺服器")
                sock.sendall((json.dumps({"type": 2})+'\n').encode('utf-8'))
                
            elif message['type'] == 3:
                msg_text = message['message'].strip()
                
                # --- 系統指令 (維持斜線開頭) ---
                if msg_text.startswith('/'):
                    parts = msg_text.split()
                    cmd = parts[0].lower()
                    
                    if cmd == '/create':
                        if len(parts) < 3: sock.sendall(json_msg("系統","用法: /create <房名> <密碼>")); continue
                        r_name, r_pass = parts[1], parts[2]
                        if r_name in rooms: sock.sendall(json_msg("系統","房間已存在")); continue
                        if room_name: leave_room(nickname, room_name)
                        me = next(c for c in client_list if c['nickname'] == nickname)
                        me['room'] = r_name; me['role'] = 'host'
                        rooms[r_name] = {'password': r_pass, 'host': nickname, 'members': [me], 'state': 'waiting', 'lock': threading.Lock(), 'game': {}}
                        room_name = r_name
                        sock.sendall(json_msg("系統", f"房間 {r_name} 建立成功，你是房主"))
                    
                    elif cmd == '/join':
                        if len(parts) < 3: sock.sendall(json_msg("系統","用法: /join <房名> <密碼>")); continue
                        r_name, r_pass = parts[1], parts[2]
                        if r_name not in rooms: sock.sendall(json_msg("系統","房間不存在")); continue
                        if rooms[r_name]['password'] != r_pass: sock.sendall(json_msg("系統","密碼錯誤")); continue
                        if len(rooms[r_name]['members']) >= MAX_PLAYERS: sock.sendall(json_msg("系統",f"房間滿了")); continue
                        if rooms[r_name]['state'] == 'playing': sock.sendall(json_msg("系統","遊戲進行中無法加入")); continue
                        if room_name: leave_room(nickname, room_name)
                        me = next(c for c in client_list if c['nickname'] == nickname)
                        me['room'] = r_name; me['role'] = 'user'
                        rooms[r_name]['members'].append(me)
                        room_name = r_name
                        broadcast_room(room_name, "系統", f"{nickname} 加入房間")
                        sock.sendall(json_msg("系統", f"已加入房間 {room_name}"))
                    
                    elif cmd == '/leave':
                        leave_room(nickname, room_name); room_name = None; sock.sendall(json_msg("系統","已離開房間"))
                    
                    elif cmd == '/who':
                        if room_name in rooms:
                            host_name = rooms[room_name]['host']; display_list = []
                            is_playing = rooms[room_name].get('state') == 'playing'
                            for m in rooms[room_name]['members']:
                                role_tag = " (房主) " if m['nickname'] == host_name else ""
                                alive_status = " ✅" if is_playing and m.get('alive') else (" ❌" if is_playing else "")
                                display_list.append(m['nickname'] + role_tag + alive_status)
                            sock.sendall(json_msg("系統", f"房間成員:\n" + "\n".join(display_list)))
                        else: sock.sendall(json_msg("系統","你不在房間內"))
                        
                    elif cmd == '/start' or (cmd == '/game' and len(parts)>1 and parts[1]=='start'):
                        if room_name in rooms:
                            if rooms[room_name]['host'] == nickname:
                                if len(rooms[room_name]['members']) >= 4:
                                    rooms[room_name]['state'] = 'playing'; broadcast_room(room_name, "系統", "遊戲開始！")
                                    assign_roles(room_name)
                                    if rooms[room_name]['state'] == 'playing':
                                        threading.Thread(target=start_werewolf_game, args=(room_name,), daemon=True).start()
                                else: sock.sendall(json_msg("系統", f"人數不足 (至少 4 人)"))
                            else: sock.sendall(json_msg("系統","只有房主可以開始遊戲"))
                        else: sock.sendall(json_msg("系統", "請先加入房間"))

                    elif cmd == '/help':
                        help_txt = (
                            "\n==================== 使用說明 ===================="
                            "\n 1️⃣ 　創建房間：　　　　　　　　　　輸入 /create"
                            "\n 2️⃣ 　加入房間：　　　　　　　　　　輸入 /join"
                            "\n 3️⃣ 　查看房間成員：　　　　　　　　輸入 /who"
                            "\n 4️⃣ 　離開房間：　　　　　　　　　　輸入 /leave"
                            "\n 5️⃣ 　開始遊戲（host 才可）：　　　 輸入 /start"
                            "\n 6️⃣ 　指令集查詢：　　　　　　　　　輸入 /help"
                            "\n==================== 遊戲指令 ===================="
                            "\n ⭐  直接輸入不需要斜線 ❗"
                            "\n 1️⃣ 　白天投票：　　　　　　　　　　輸入 投票 <名>"
                            "\n 2️⃣ 　狼人/狼王： 　　　　　　　　　輸入 殺 <名>"
                            "\n 3️⃣ 　狼王(白天)：　　　　　　　　　輸入 報復 <名>"
                            "\n 4️⃣ 　預言家：　　　　　　　　　　　輸入 查驗 <名>"
                            "\n 5️⃣ 　守衛：　　　　　　　　　　　　輸入 守護 <名>"
                            "\n 6️⃣ 　女巫使用毒藥：　　　　　　　　輸入 毒藥 <名>"
                            "\n 7️⃣ 　女巫使用解藥：　　　　　　　　輸入 解藥 <名>"
                            "\n 8️⃣ 　女巫不使用藥水：　　　　　　　輸入 不使用"
                            "\n 9️⃣ 　獵人：　　　　　　　　　　　　輸入 開槍 <名>"
                            "\n==================================================="
                            "\n 小提示：房間內直接輸入文字即可聊天 "
                            "\n==================================================="
                        )
                        sock.sendall(json_msg("系統", help_txt))
                    else: sock.sendall(json_msg("系統", "未知指令"))

                # --- 遊戲進行中邏輯 (包含所有角色指令) ---
                elif room_name and rooms[room_name].get('state') == 'playing':
                    game = rooms[room_name].get('game', {}); phase = game.get('phase')
                    me = next((m for m in rooms[room_name]['members'] if m['nickname'] == nickname), None)
                    parts = msg_text.split()
                    
                    if me:
                        # 1. 投票 (白天)
                        if parts[0] == '投票' and phase == 'day' and me.get('alive') and not me.get('is_idiot'):
                            if len(parts) < 2: sock.sendall(json_msg("系統", "用法: 投票 <名字> 或 投票 棄票"))
                            else:
                                target = parts[1]
                                if target == "棄票" or check_alive_target(room_name, target):
                                    with rooms[room_name]['lock']: game['day_votes'][nickname] = target
                                    sock.sendall(json_msg("系統", f"你投給了：{target}"))
                                else: sock.sendall(json_msg("系統", "目標不存在或已死亡"))

                        # 2. 守護 (守衛)
                        elif parts[0] == '守護' and phase == 'guard' and me.get('alive') and me.get('game_role') == '守衛':
                             if len(parts) < 2: send_private_msg(sock, "系統", "用法: 守護 <玩家名>") # 統一格式
                             else:
                                 target = parts[1]
                                 if not check_alive_target(room_name, target): send_private_msg(sock, "系統", "目標不存在或已死亡")
                                 elif target == rooms[room_name]['game'].get('last_guard_target'): send_private_msg(sock, "系統", "不能連續守護同一個人")
                                 else:
                                     with rooms[room_name]['lock']: game['guard_target'] = target
                                     send_private_msg(sock, "系統", f"守護：{target}")

                        # 3. 查驗 (預言家)
                        elif parts[0] == '查驗' and phase == 'seer' and me.get('alive') and me.get('game_role') == '預言家':
                             if len(parts) < 2: send_private_msg(sock, "系統", "用法: 查驗 <玩家名>") # 統一格式
                             else:
                                 target = parts[1]
                                 if not check_alive_target(room_name, target): send_private_msg(sock, "系統", "目標不存在或已死亡")
                                 else:
                                     with rooms[room_name]['lock']: game['seer_target'] = target
                                     send_private_msg(sock, "系統", f"查驗：{target}")

                        # 4. 殺 (狼人)
                        elif parts[0] == '殺' and phase == 'wolf' and me.get('alive') and me['game_role'] in ['狼人', '狼王']:
                            if len(parts) < 2: send_private_msg(sock, "系統", "用法: 殺 <玩家名>") # 統一格式
                            else:
                                target = parts[1]
                                target_obj = next((m for m in rooms[room_name]['members'] if m['nickname'] == target), None)
                                
                                # 取得非狼人隊友的存活名單，用於再次提示
                                all_wolves_names = [m['nickname'] for m in rooms[room_name]['members'] if m['game_role'] in ['狼人', '狼王']]
                                target_list_str = get_alive_list_str(room_name, exclude_list=all_wolves_names)

                                if target_obj and target_obj['game_role'] in ['狼人', '狼王']:
                                    send_private_msg(sock, "系統", "不能殺隊友")
                                elif target not in target_list_str.split(', '): # 檢查是否在可殺的存活名單中
                                    send_private_msg(sock, "系統", f"目標不存在或已死亡/為隊友\n可選擇目標：{target_list_str}")
                                else:
                                    with rooms[room_name]['lock']: game['wolves_votes'][nickname] = target
                                    send_private_msg(sock, "系統", f"選擇殺：{target}")
                                    for c in rooms[room_name]['members']:
                                        if c.get('game_role') in ['狼人', '狼王'] and c.get('alive'):
                                            send_private_msg(c['socket'], "系統", f"(隊友) {nickname} 殺 {target}")

                        # 5. 女巫 (毒藥/解藥)
                        elif phase == 'witch' and me.get('alive') and me['game_role'] == '女巫' and parts[0] in ['毒藥', '解藥', '不使用']:
                            if parts[0] == '不使用': 
                                pass # 不需 target，直接 pass
                            elif len(parts) < 2: 
                                send_private_msg(sock, "系統", "用法: 毒藥 <玩家名> 或 解藥 <玩家名>") # 統一格式
                                continue
                            else:
                                target = parts[1]
                                if not check_alive_target(room_name, target): send_private_msg(sock, "系統", "目標不存在或已死亡"); continue
                                if parts[0] == '解藥' and not me.get('can_use_potion'): send_private_msg(sock, "系統", "解藥已用過"); continue
                                if parts[0] == '毒藥' and not me.get('can_use_poison'): send_private_msg(sock, "系統", "毒藥已用過"); continue
                                
                                type_ = 'save' if parts[0] == '解藥' else 'poison'
                                with rooms[room_name]['lock']: game['witch_action'] = {'type': type_, 'target': target}
                            
                            # 修正：不使用時也不會有 parts[1]
                            selected_action = parts[0]
                            selected_target = parts[1] if len(parts) > 1 else ''
                            send_private_msg(sock, "系統", f"已選擇：{selected_action} {selected_target}")

                        # 6. 狼王報復
                        elif parts[0] == '報復' and phase == 'wolfking_revenge' and not me.get('alive') and me['game_role'] == '狼王':
                             if len(parts) < 2: send_private_msg(sock, "系統", "用法: 報復 <玩家名>") # 統一格式
                             else:
                                 target = parts[1]
                                 if check_alive_target(room_name, target):
                                     with rooms[room_name]['lock']: game['revenge_target'] = target
                                     send_private_msg(sock, "系統", f"報復目標：{target}")
                                 else: send_private_msg(sock, "系統", "目標錯誤")

                        # 7. 獵人開槍
                        elif parts[0] == '開槍' and phase == 'hunter_revenge' and not me.get('alive') and me['game_role'] == '獵人':
                             if len(parts) < 2: send_private_msg(sock, "系統", "用法: 開槍 <玩家名> 或 開槍 棄槍") # 統一格式
                             else:
                                 target = parts[1]
                                 if target == '棄槍':
                                      with rooms[room_name]['lock']: game['revenge_target'] = '棄槍'
                                      send_private_msg(sock, "系統", "選擇棄槍")
                                 elif check_alive_target(room_name, target):
                                      with rooms[room_name]['lock']: game['revenge_target'] = target
                                      send_private_msg(sock, "系統", f"帶走目標：{target}")
                                 else: send_private_msg(sock, "系統", "目標錯誤")

                        # 8. 聊天 (白天廣播 / 夜晚自言自語 / 鬼魂)
                        else:
                            # 如果玩家嘗試在錯誤階段輸入指令，提示錯誤，否則視為聊天
                            potential_cmds = ['投票', '守護', '查驗', '殺', '毒藥', '解藥', '報復', '開槍']
                            if parts[0] in potential_cmds:
                                send_private_msg(sock, "系統", "當前階段無法使用此指令或身分不符")
                            elif me.get('alive'):
                                if phase == 'day': broadcast_room(room_name, nickname, msg_text)
                                else: broadcast_room(room_name, nickname, msg_text) # 夜晚自言自語
                            else:
                                broadcast_ghost_room(room_name, nickname, msg_text)

                # 大廳聊天
                else:
                    if room_name: broadcast_room(room_name, nickname, msg_text)
                    else: sock.sendall(json_msg("系統", "請先加入房間"))

        except Exception as e:
            print(f"Error: {e}"); break

    if nickname:
        if room_name: leave_room(nickname, room_name)
        client_list[:] = [c for c in client_list if c['nickname'] != nickname]
    sock.close()

def main():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try: s.bind((bind_ip, bind_port))
    except OSError: return
    s.listen(5); print(f"伺服器啟動於{bind_ip} {bind_port}...")
    print("多人聊天室伺服器啟動中...")
    print("\n等待新連線中...\n")

    while True:
        try: conn, addr = s.accept(); threading.Thread(target=client_thread, args=(conn, addr), daemon=True).start()
        except KeyboardInterrupt: break
    s.close()

if __name__ == "__main__":
    main()
