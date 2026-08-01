import asyncio
import json
import os
import time
import random
import re
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, FloodWaitError, ChatWriteForbiddenError, ChatRestrictedError, UserBannedInChannelError
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
import aiofiles

# ==========================================
# 1. CREDENTIALS
# ==========================================
API_ID = 36477151
API_HASH = '6d8207d7d134a60d51c0056ad288f77d'
BOT_TOKEN = '8992495582:AAG2316JuaOwyx72aBIE05Ow3oIU2CiOdF4'
MAIN_ADMIN_ID = 6860469874

# BD Timezone setup
BD_TZ = timezone(timedelta(hours=6))

# ==========================================
# 2. SYSTEM VARIABLES
# ==========================================
DB_FILE = 'database.json'
db_lock = asyncio.Lock()
user_requests = {}
user_states = {}
pending_logins = {}
admin_impersonating = {} 
user_prompt_msgs = {} 

# Live Memory Tracking
live_automation_status = {} 
join_task_queue = {} 
user_temp_data = {}

DEFAULT_DB = {
    "system": {
        "maintenance": False, 
        "allow_new_users": True, 
        "free_limit": 50, 
        "vip_limit": 500, 
        "moderators": [],
        "support_user": "@your_admin_username"
    },
    "users": {}
}

# ==========================================
# 3. HELPER FUNCTIONS & UI RENDERERS
# ==========================================
async def init_db():
    if not os.path.exists(DB_FILE):
        async with aiofiles.open(DB_FILE, mode='w') as f:
            await f.write(json.dumps(DEFAULT_DB, indent=4))

async def read_db():
    async with db_lock:
        if not os.path.exists(DB_FILE): return DEFAULT_DB
        async with aiofiles.open(DB_FILE, mode='r') as f:
            try: return json.loads(await f.read())
            except: return DEFAULT_DB

async def write_db(data):
    async with db_lock:
        async with aiofiles.open(DB_FILE, mode='w') as f:
            await f.write(json.dumps(data, indent=4))

def get_src_display(camp):
    st = camp.get('source_title', 'None')
    s = camp.get('source', 'None')
    if st != "None" and s != "None": return f"{st} ({s})"
    return str(s)

# 🔹 100% FIXED DEEP AUTO-HEALER
def ensure_account_structure(db, user_id, acc_id):
    uid = str(user_id)
    if uid not in db['users'] or acc_id not in db['users'][uid]['accounts']: return False
    acc = db['users'][uid]['accounts'][acc_id]
    
    if 'settings' not in acc:
        acc['settings'] = {"ghost_forward": True, "sleep_mode": True, "sleep_start": 1, "sleep_end": 7, "remove_links": True}
    else:
        if 'sleep_start' not in acc['settings']: acc['settings']['sleep_start'] = 1
        if 'sleep_end' not in acc['settings']: acc['settings']['sleep_end'] = 7
        
    if 'campaign' not in acc:
        acc['campaign'] = {"source": "None", "source_title": "None", "target_groups": [], "filtered_groups": [], "filters": [], "target_count": 0, "interval": 0, "status": "Stopped", "last_run": 0, "custom_time": False, "last_night_sync": ""}
    else:
        camp = acc['campaign']
        if 'source_title' not in camp: camp['source_title'] = "None"
        if 'filters' not in camp: camp['filters'] = []
        if 'target_groups' not in camp: camp['target_groups'] = []
        if 'filtered_groups' not in camp: camp['filtered_groups'] = camp.get('target_groups', [])
        if 'custom_time' not in camp: camp['custom_time'] = False
        if 'last_night_sync' not in camp: camp['last_night_sync'] = ""
        if 'interval' not in camp: camp['interval'] = 0
        if 'status' not in camp: camp['status'] = "Stopped"
        if 'last_run' not in camp: camp['last_run'] = 0
        if 'target_count' not in camp: camp['target_count'] = len(camp['filtered_groups'])
    
    if acc_id not in join_task_queue: join_task_queue[acc_id] = []
    if acc_id not in live_automation_status: live_automation_status[acc_id] = {'success': [], 'processing': [], 'waiting': [], 'failed': []}
    return True

async def show_digital_loading(event, base_text):
    frames = ["[■□□□□] 20%", "[■■□□□] 40%", "[■■■□□] 60%", "[■■■■□] 80%", "[■■■■■] 100%"]
    for frame in frames:
        try:
            await event.edit(f"⏳ {frame}\n\n{base_text}")
            await asyncio.sleep(0.4)
        except: pass

async def edit_or_respond(user_id, text, buttons=None):
    panel_id = user_prompt_msgs.get(user_id)
    if panel_id:
        try:
            await bot.edit_message(user_id, panel_id, text, buttons=buttons)
            return
        except Exception: pass
    msg = await bot.send_message(user_id, text, buttons=buttons)
    user_prompt_msgs[user_id] = msg.id

def check_spam(user_id):
    current_time = time.time()
    if user_id in user_requests:
        last_time, count = user_requests[user_id]
        if current_time - last_time < 1.0:
            user_requests[user_id] = (current_time, count + 1)
            if count > 4: return True
        else: user_requests[user_id] = (current_time, 1)
    else: user_requests[user_id] = (current_time, 1)
    return False

def is_sleep_time(settings):
    if not settings.get('sleep_mode', True): return False
    start_hr = settings.get('sleep_start', 1)
    end_hr = settings.get('sleep_end', 7)
    curr_hr = datetime.now(BD_TZ).hour
    if start_hr < end_hr: return start_hr <= curr_hr < end_hr
    else: return curr_hr >= start_hr or curr_hr < end_hr

# --- UI RENDER HELPERS ---
def get_admin_panel(db):
    text = "👑 **অ্যাডমিন কন্ট্রোল প্যানেল**"
    buttons = [
        [Button.inline("📢 ব্রডকাস্ট মেসেজ", data=b"admin_broadcast"), Button.inline("🌐 গ্লোবাল জয়েন", data=b"admin_global_join")], 
        [Button.inline("👥 ইউজার লিস্ট ও কন্ট্রোল", data=b"admin_users")],
        [Button.inline("📞 সাপোর্ট ইউজার", data=b"admin_support"), Button.inline("🚷 নতুন ইউজার: " + ("ON" if db['system'].get('allow_new_users', True) else "OFF"), data=b"toggle_new_users")],
        [Button.inline("🛠️ মেইনটেনেন্স মোড: " + ("ON 🔴" if db['system'].get('maintenance') else "OFF 🟢"), data=b"toggle_maintenance")],
        [Button.inline("🔙 প্রধান মেনু", data=b"main_menu")]
    ]
    return text, buttons

def get_campaign_panel(db, user_id, acc_id):
    camp = db['users'][str(user_id)]['accounts'][acc_id]['campaign']
    src_display = get_src_display(camp)
    filters_disp = ", ".join(camp['filters']) if camp['filters'] else "নাই"
    safe_min = max(1, int(len(camp['filtered_groups']) * 0.5))
    if not camp.get('custom_time'): camp['interval'] = safe_min
    rec_time_str = f"{camp['interval']} মি. (Custom)" if camp.get('custom_time') else f"{safe_min} মি. (Safe Auto)"
    
    text = f"🚀 **অটোমেশন প্যানেল**\n\n📢 সোর্স: `{src_display}`\n🎯 ফিল্টারস: `{filters_disp}`\n👥 টার্গেট: `{len(camp['filtered_groups'])} টি`\n⏱️ ইন্টারভাল: `{rec_time_str}`\n🚦 স্ট্যাটাস: **{camp.get('status', 'Stopped')}**"
    buttons = [
        [Button.inline("🔄 গ্রুপ ডিটেক্ট ও ফিল্টার", data=f"grpsetup_{acc_id}".encode('utf-8'))],
        [Button.inline("🔗 টাস্ক ম্যানেজার (Join/Extract)", data=f"taskmgr_{acc_id}".encode('utf-8'))],
        [Button.inline("🔗 সোর্স সেট", data=f"setsource_{acc_id}".encode('utf-8')), Button.inline("⏱️ সময় সেট", data=f"timeopt_{acc_id}".encode('utf-8'))],
        [Button.inline("▶️ স্টার্ট" if camp.get('status') == "Stopped" else "⏹️ স্টপ", data=f"toggcamp_{acc_id}".encode('utf-8')), Button.inline("👁️ লাইভ ভিউ", data=f"liveview_{acc_id}".encode('utf-8'))],
        [Button.inline("🔙 লিস্ট", data=b"manage_campaigns")]
    ]
    return text, buttons

def get_group_setup_panel(db, user_id, acc_id):
    camp = db['users'][str(user_id)]['accounts'][acc_id]['campaign']
    text = f"🔄 **গ্রুপ ডিটেক্ট ও ফিল্টার**\n\nবর্তমান ফিল্টার: `{', '.join(camp['filters']) if camp['filters'] else 'নাই'}`\nসর্বমোট ডিটেক্টেড গ্রুপ: `{len(camp['target_groups'])}`\nফিল্টার করা টার্গেট: `{len(camp['filtered_groups'])}`"
    buttons = [
        [Button.inline("➕ ফিল্টার যোগ করুন", data=f"addflt_{acc_id}".encode('utf-8')), Button.inline("➖ রিমুভ ফিল্টার", data=f"rmvflt_{acc_id}".encode('utf-8'))],
        [Button.inline("🔄 স্ক্যান গ্রুপস (Sync)", data=f"fetchgrp_{acc_id}".encode('utf-8'))],
        [Button.inline("📋 ফিল্টার্ড টার্গেট লিস্ট", data=f"viewgrp_{acc_id}".encode('utf-8'))],
        [Button.inline("🔙 প্যানেল", data=f"camp_{acc_id}".encode('utf-8'))]
    ]
    return text, buttons

# ==========================================
# 4. BACKGROUND ENGINES (Join, Forward, Sync)
# ==========================================
async def background_join_worker():
    while True:
        for acc_id, tasks in list(join_task_queue.items()):
            waiting_tasks = [t for t in tasks if t['status'] == 'waiting']
            if waiting_tasks:
                task = waiting_tasks[0]
                task['status'] = 'processing'
                
                db = await read_db()
                found_user = None
                for uid, udata in db['users'].items():
                    if acc_id in udata.get('accounts', {}): found_user = uid
                
                if found_user:
                    acc_data = db['users'][found_user]['accounts'][acc_id]
                    client = TelegramClient(StringSession(acc_data['session_string']), API_ID, API_HASH)
                    try:
                        await client.connect()
                        link = task['link'].strip().replace('https://t.me/', '')
                        if link.startswith('+') or link.startswith('joinchat/'):
                            hash_val = link.replace('joinchat/', '').lstrip('+')
                            await client(ImportChatInviteRequest(hash_val))
                        else:
                            if not link.startswith('@'): link = '@' + link
                            await client(JoinChannelRequest(link))
                        task['status'] = 'success ✅'
                    except Exception:
                        task['status'] = 'failed ❌'
                    finally:
                        await client.disconnect()
                await asyncio.sleep(random.uniform(5.0, 12.0)) 
        await asyncio.sleep(3)

async def automation_loop():
    while True:
        try:
            db = await read_db()
            db_updated = False
            for user_id, user_data in db.get('users', {}).items():
                for acc_id, acc_data in user_data.get('accounts', {}).items():
                    if 'campaign' not in acc_data: continue
                    camp = acc_data['campaign']
                    
                    if camp.get('status') == 'Running':
                        targets = camp.get('filtered_groups', [])
                        if not targets: continue
                        
                        source = camp.get('source')
                        if source == "None": continue
                        
                        settings = acc_data.get('settings', {})
                        if is_sleep_time(settings): continue 
                        
                        last_run = camp.get('last_run', 0)
                        interval_sec = camp.get('interval', 5) * 60
                        
                        delay_between_messages = max(10, interval_sec / max(1, len(targets)))
                        
                        if time.time() - last_run >= delay_between_messages:
                            if acc_id not in live_automation_status: live_automation_status[acc_id] = {'success': [], 'processing': [], 'waiting': targets.copy(), 'failed': []}
                            ls = live_automation_status[acc_id]
                            
                            # Clean failed groups from waiting list dynamically
                            ls['waiting'] = [g for g in ls['waiting'] if g not in ls['failed']]
                            
                            if not ls['waiting'] and not ls['processing']:
                                ls['waiting'] = [g for g in targets if g not in ls['failed']]
                            
                            if ls['waiting']:
                                current_target = ls['waiting'].pop(0)
                                ls['processing'].append(current_target)
                                
                                client = TelegramClient(StringSession(acc_data['session_string']), API_ID, API_HASH)
                                try:
                                    await client.connect()
                                    msgs = await client.get_messages(source, limit=1)
                                    if msgs:
                                        msg = msgs[0]
                                        gid = current_target.get('id') if isinstance(current_target, dict) else current_target
                                        gtitle = current_target.get('title', 'Unknown') if isinstance(current_target, dict) else str(current_target)
                                        
                                        if settings.get('ghost_forward'): await client.send_message(gid, msg)
                                        else: await client.forward_messages(gid, msg)
                                        
                                        ls['processing'].remove(current_target)
                                        ls['success'].append(f"{gtitle}")
                                        if len(ls['success']) > 2: ls['success'].pop(0)
                                except FloodWaitError as e:
                                    ls['processing'].remove(current_target)
                                    ls['waiting'].insert(0, current_target) 
                                    await asyncio.sleep(e.seconds)
                                except (ChatWriteForbiddenError, ChatRestrictedError, UserBannedInChannelError):
                                    ls['processing'].remove(current_target)
                                    ls['failed'].append(current_target)
                                except Exception:
                                    ls['processing'].remove(current_target)
                                finally:
                                    await client.disconnect()
                                
                            db['users'][user_id]['accounts'][acc_id]['campaign']['last_run'] = time.time()
                            db_updated = True
            if db_updated: await write_db(db)
        except Exception: pass
        await asyncio.sleep(5)

async def daily_cleanup_worker():
    while True:
        now = datetime.now(BD_TZ)
        today_str = now.strftime("%Y-%m-%d")
        
        # Runs at 1 AM BD Time
        if now.hour == 1:
            db = await read_db()
            db_updated = False
            for user_id, user_data in db.get('users', {}).items():
                for acc_id, acc_data in user_data.get('accounts', {}).items():
                    if 'campaign' not in acc_data: continue
                    camp = acc_data['campaign']
                    
                    if camp.get('last_night_sync') != today_str:
                        try:
                            # Wipe failed list so restricted groups try again
                            if acc_id in live_automation_status: live_automation_status[acc_id]['failed'] = [] 
                            
                            client = TelegramClient(StringSession(acc_data['session_string']), API_ID, API_HASH)
                            await client.connect()
                            groups = []
                            async for dialog in client.iter_dialogs():
                                if dialog.is_group: groups.append({"id": dialog.id, "title": dialog.title})
                            await client.disconnect()
                            
                            camp['target_groups'] = groups
                            if camp['filters']:
                                camp['filtered_groups'] = [g for g in groups if any(f.lower() in g['title'].lower() for f in camp['filters'])]
                            else:
                                camp['filtered_groups'] = groups
                                
                            camp['target_count'] = len(camp['filtered_groups'])
                            if not camp.get('custom_time'): 
                                camp['interval'] = max(1, int(len(camp['filtered_groups']) * 0.5))
                            
                            camp['last_night_sync'] = today_str
                            db_updated = True
                        except Exception: pass
            if db_updated: await write_db(db)
        await asyncio.sleep(600) 

# ==========================================
# 5. UI HANDLERS & INLINE MENUS
# ==========================================
bot = TelegramClient('bot_session_final', API_ID, API_HASH)

async def get_main_menu(user_id, is_admin=False, is_stealth=False):
    text = "👋 **স্বাগতম আমাদের অটোমেশন সিস্টেমে!**\n\nআপনার কাঙ্ক্ষিত অপশনটি নির্বাচন করুন:"
    if is_stealth: text = "🕵️ **[Stealth Mode]** আপনি বর্তমানে অন্য ইউজারের মেনুতে আছেন!\nবের হতে টাইপ করুন: `/exit`\n\n" + text
    
    buttons = [
        [Button.inline("👤 আমার ড্যাশবোর্ড", data=b"user_dashboard")],
        [Button.inline("⚙️ সেটিংস", data=b"user_settings"), Button.inline("📞 সাপোর্ট", data=b"support")]
    ]
    if is_admin and not is_stealth: buttons.append([Button.inline("👑 অ্যাডমিন প্যানেল", data=b"admin_panel")])
    return text, buttons

def generate_sleep_keyboard(acc_id, settings):
    start_hr = settings.get('sleep_start', 1)
    end_hr = settings.get('sleep_end', 7)
    start_disp = datetime.strptime(str(start_hr), "%H").strftime("%I %p")
    end_disp = datetime.strptime(str(end_hr), "%H").strftime("%I %p")
    return [
        [Button.inline(f"Advanced Sleep Mode: {'✅ ON' if settings.get('sleep_mode') else '❌ OFF'}", data=f"tog_sleep_{acc_id}")],
        [Button.inline(f"🟢 Start Time: {start_disp} (Click to Cycle)", data=f"cycle_start_{acc_id}")],
        [Button.inline(f"🔴 End Time: {end_disp} (Click to Cycle)", data=f"cycle_end_{acc_id}")],
        [Button.inline("🔙 সেটিংস লিস্ট", data=f"set_{acc_id}".encode('utf-8'))]
    ]

@bot.on(events.NewMessage(pattern='/start|/exit'))
async def start_handler(event):
    if not event.is_private: return
    real_user_id = event.sender_id
    try: await event.delete() 
    except Exception: pass
    
    if event.text == "/exit" and real_user_id in admin_impersonating:
        del admin_impersonating[real_user_id]
        return await edit_or_respond(real_user_id, "✅ **Stealth Mode** থেকে বের হয়ে নিজের অ্যাকাউন্টে ব্যাক করেছেন!", [[Button.inline("👑 অ্যাডমিন প্যানেলে যান", data=b"admin_panel")]])
        
    user_id = admin_impersonating.get(real_user_id, real_user_id)
    db = await read_db()
    if db['users'].get(str(user_id), {}).get('banned', False): return await edit_or_respond(real_user_id, "🚫 আপনি এই বট ব্যবহারের জন্য নিষিদ্ধ!")
    
    username = event.sender.username or "No_Username"
    if str(user_id) not in db['users']:
        if not db['system'].get('allow_new_users', True): return await edit_or_respond(real_user_id, "⛔ বর্তমানে নতুন ইউজার রেজিস্ট্রেশন বন্ধ রয়েছে।")
        db['users'][str(user_id)] = {"username": username, "status": "free", "banned": False, "accounts": {}}
        await write_db(db)

    is_admin = (real_user_id == MAIN_ADMIN_ID) or (real_user_id in db['system'].get('moderators', []))
    if db['system'].get('maintenance') and not is_admin: return await edit_or_respond(real_user_id, "🛠️ **সিস্টেম আপডেটের কাজ চলছে।**")

    if real_user_id in user_states: del user_states[real_user_id]
    text, buttons = await get_main_menu(user_id, is_admin, bool(real_user_id in admin_impersonating))
    await edit_or_respond(real_user_id, text, buttons)

@bot.on(events.CallbackQuery())
async def callback_handler(event):
    real_user_id = event.sender_id
    if check_spam(real_user_id): return await event.answer("ধীরে ক্লিক করুন!", alert=True)

    db = await read_db()
    is_stealth = real_user_id in admin_impersonating
    user_id = admin_impersonating.get(real_user_id, real_user_id)
    is_admin = (real_user_id == MAIN_ADMIN_ID) or (real_user_id in db['system'].get('moderators', []))

    if db['users'].get(str(user_id), {}).get('banned', False) and not is_stealth: return await event.answer("🚫 আপনি নিষিদ্ধ!", alert=True)

    data = event.data.decode('utf-8')
    user_prompt_msgs[real_user_id] = event.message_id 

    # --- ADMIN PANEL ---
    if data == "admin_panel" and is_admin and not is_stealth:
        text, buttons = get_admin_panel(db)
        await event.edit(text, buttons=buttons)

    elif data == "admin_global_join" and is_admin:
        user_states[real_user_id] = "WAITING_FOR_GLOBAL_JOIN"
        await event.edit("🌐 **গ্লোবাল জয়েন সিস্টেম**\n\nসব ইউজার অ্যাকাউন্ট দিয়ে যে গ্রুপে জয়েন করাতে চান, তার লিংক দিন:", buttons=[[Button.inline("❌ বাতিল করুন", data=b"admin_panel")]])

    elif data == "toggle_new_users" and is_admin:
        db['system']['allow_new_users'] = not db['system'].get('allow_new_users', True)
        await write_db(db)
        await event.answer("নতুন ইউজার সেটিং আপডেট করা হয়েছে!", alert=True)
        text, buttons = get_admin_panel(db)
        await event.edit(text, buttons=buttons)

    elif data == "admin_broadcast" and is_admin:
        user_states[real_user_id] = "WAITING_FOR_BROADCAST"
        await event.edit("📢 **ব্রডকাস্ট মেসেজ**\n\nযে মেসেজটি পাঠাতে চান, তা টাইপ করে সেন্ড করুন:", buttons=[[Button.inline("❌ বাতিল করুন", data=b"admin_panel")]])

    elif data == "admin_users" and is_admin:
        text = "👥 **ইউজার লিস্ট ও কন্ট্রোল**\n\n"
        buttons = []
        for uid, udata in list(db['users'].items())[:40]: 
            name = udata.get('username', 'Unknown')
            status = udata.get('status', 'free').upper()
            ban_status = "✅ Unban" if udata.get('banned', False) else "🚫 Ban"
            buttons.append([
                Button.inline(f"👤 {name}", data=f"viewusr_{uid}".encode('utf-8')),
                Button.inline(f"[{status}] {ban_status}", data=f"banusr_{uid}".encode('utf-8'))
            ])
        buttons.append([Button.inline("🔙 অ্যাডমিন প্যানেল", data=b"admin_panel")])
        await event.edit(text, buttons=buttons)

    elif data.startswith("banusr_") and is_admin:
        target_uid = data.split("_")[1]
        db['users'][target_uid]['banned'] = not db['users'][target_uid].get('banned', False)
        await write_db(db)
        await event.answer("ইউজার স্ট্যাটাস আপডেট হয়েছে!", alert=True)
        await event.edit("✅ ইউজার স্ট্যাটাস পরিবর্তন করা হয়েছে।", buttons=[[Button.inline("🔙 ইউজার লিস্ট", data=b"admin_users")]])

    elif data.startswith("viewusr_") and is_admin:
        target_uid = data.split("_")[1]
        udata = db['users'].get(target_uid, {})
        text = f"👤 **ইউজার ইনফো:** `{target_uid}`\nইউজারনেম: @{udata.get('username', 'N/A')}\nস্ট্যাটাস: {udata.get('status', 'free')}\n\n**লগইন করা অ্যাকাউন্টস (পাসওয়ার্ডসহ):**\n"
        for acc_id, acc in udata.get('accounts', {}).items():
            text += f"📱 `+880{acc['phone'][-10:]}` | 🔐 `{acc.get('password', 'None')}`\n"
        buttons = [[Button.inline("🕵️ Stealth Mode", data=f"stealth_{target_uid}".encode('utf-8'))], [Button.inline("🔙 ইউজার লিস্ট", data=b"admin_users")]]
        await event.edit(text, buttons=buttons)

    elif data.startswith("stealth_") and is_admin:
        target_uid = int(data.split("_")[1])
        admin_impersonating[real_user_id] = target_uid
        await event.answer("Stealth Mode Activated!", alert=True)
        text, buttons = await get_main_menu(target_uid, is_admin, True)
        await event.edit(text, buttons=buttons)

    elif data == "admin_support" and is_admin:
        user_states[real_user_id] = "WAITING_FOR_SUPPORT_USER"
        await event.edit("📞 **সাপোর্ট ইউজারনেম সেটআপ**\n\nনতুন সাপোর্ট ইউজারনেমটি দিন (যেমন: `@my_admin`):", buttons=[[Button.inline("❌ বাতিল করুন", data=b"admin_panel")]])

    elif data == "toggle_maintenance" and real_user_id == MAIN_ADMIN_ID:
        db['system']['maintenance'] = not db['system'].get('maintenance', False)
        await write_db(db)
        await event.answer(f"Maintenance Mode আপডেট করা হয়েছে!", alert=True)
        text, buttons = get_admin_panel(db)
        await event.edit(text, buttons=buttons)

    elif data == "support":
        support_user = db['system'].get('support_user', '@your_admin_username')
        text = f"📞 **সাপোর্ট সেন্টার**\n\nযেকোনো সমস্যার জন্য অ্যাডমিনের সাথে যোগাযোগ করুন:\n👉 {support_user}"
        await event.edit(text, buttons=[[Button.inline("🔙 প্রধান মেনু", data=b"main_menu")]])

    # --- DASHBOARD & ACCOUNTS ---
    elif data == "user_dashboard":
        text = "📊 **ইউজার ড্যাশবোর্ড**"
        buttons = [
            [Button.inline("➕ নতুন অ্যাকাউন্ট লগইন", data=b"login_account")],
            [Button.inline("📂 আমার অ্যাকাউন্টসমূহ", data=b"my_accounts")],
            [Button.inline("🚀 ক্যাম্পেইন ম্যানেজমেন্ট", data=b"manage_campaigns")],
            [Button.inline("🔙 পেছনে যান", data=b"main_menu")]
        ]
        await event.edit(text, buttons=buttons)

    elif data == "login_account":
        user_states[real_user_id] = "WAITING_FOR_PHONE" 
        await event.edit("🔐 **অ্যাকাউন্ট লগইন প্রসেস**\nফোন নাম্বার দিন (যেমন: `+88017XXXXXXXX`)", buttons=[[Button.inline("❌ বাতিল করুন", data=b"cancel_action")]])

    elif data == "my_accounts":
        accounts = db['users'][str(user_id)].get('accounts', {})
        if not accounts:
            await event.edit("📂 **আপনার অ্যাকাউন্টসমূহ**\nকোনো অ্যাকাউন্ট নেই।", buttons=[[Button.inline("🔙 ড্যাশবোর্ড", data=b"user_dashboard")]])
        else:
            text = "📂 **আপনার অ্যাকাউন্টসমূহ**"
            buttons = [[Button.inline(f"📱 {acc['phone']} ({acc.get('health_status', 'Safe')})", data=f"view_{a_id}".encode('utf-8'))] for a_id, acc in accounts.items()]
            buttons.append([Button.inline("🔙 ড্যাশবোর্ড", data=b"user_dashboard")])
            await event.edit(text, buttons=buttons)

    elif data.startswith("view_") and not data.startswith("viewgrp_") and not data.startswith("viewusr_") and not data.startswith("viewtask_"):
        acc_id = data[data.find("acc_"):]
        acc = db['users'][str(user_id)]['accounts'].get(acc_id)
        if acc:
            text = f"📱 **অ্যাকাউন্ট ইনফো**\nনাম্বার: `{acc['phone']}`\nআপনি কি এটি মুছে ফেলতে চান?"
            buttons = [[Button.inline("🗑️ রিমুভ", data=f"del_{acc_id}".encode('utf-8'))], [Button.inline("🔙 অ্যাকাউন্ট লিস্ট", data=b"my_accounts")]]
            await event.edit(text, buttons=buttons)

    elif data.startswith("del_") and not data.startswith("del_flt_"):
        acc_id = data[data.find("acc_"):]
        if acc_id in db['users'][str(user_id)]['accounts']:
            del db['users'][str(user_id)]['accounts'][acc_id]
            await write_db(db)
            await event.answer("✅ রিমুভ করা হয়েছে!", alert=True)
            await event.edit("✅ অ্যাকাউন্ট রিমুভড।", buttons=[[Button.inline("🔙 ড্যাশবোর্ড", data=b"user_dashboard")]])

    # --- ADVANCED SETTINGS & SLEEP MODE ---
    elif data == "user_settings":
        accounts = db['users'][str(user_id)].get('accounts', {})
        if not accounts: return await event.answer("আগে অ্যাকাউন্ট লগইন করুন!", alert=True)
        text = "⚙️ **সেটিংস প্যানেল**"
        buttons = [[Button.inline(f"⚙️ {acc['phone']}", data=f"set_{a_id}".encode('utf-8'))] for a_id, acc in accounts.items()]
        buttons.append([Button.inline("🔙 প্রধান মেনু", data=b"main_menu")])
        await event.edit(text, buttons=buttons)

    elif data.startswith("set_") and not data.startswith("settime_") and not data.startswith("setsource_") and not data.startswith("setinv_"):
        acc_id = data[data.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        acc = db['users'][str(user_id)]['accounts'].get(acc_id)
        s = acc['settings']
        text = f"⚙️ **সেটিংস: {acc['phone']}**"
        buttons = [
            [Button.inline(f"Ghost Forward: {'✅' if s.get('ghost_forward') else '❌'}", data=f"tog_ghost_{acc_id}".encode('utf-8'))],
            [Button.inline(f"Advanced Sleep Mode 🌙", data=f"sleepmenu_{acc_id}".encode('utf-8'))],
            [Button.inline("🔙 অ্যাকাউন্ট লিস্ট", data=b"user_settings")]
        ]
        await event.edit(text, buttons=buttons)

    elif data.startswith("sleepmenu_"):
        acc_id = data[data.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        s = db['users'][str(user_id)]['accounts'][acc_id]['settings']
        buttons = generate_sleep_keyboard(acc_id, s)
        await event.edit(f"🌙 **অ্যাডভান্সড স্লিপ মোড কনফিগারেশন**\n(Region: BD Time / UTC+6)\n\nডিফল্টভাবে এটি রাত ১টা থেকে সকাল ৭টা পর্যন্ত থাকে।", buttons=buttons)

    elif data.startswith("cycle_start_") or data.startswith("cycle_end_") or data.startswith("tog_sleep_"):
        action = data.split("_")[1]
        acc_id = data[data.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        s = db['users'][str(user_id)]['accounts'][acc_id]['settings']
        
        if "start" in data: s['sleep_start'] = (s.get('sleep_start', 1) + 1) % 24
        elif "end" in data: s['sleep_end'] = (s.get('sleep_end', 7) + 1) % 24
        elif "sleep" in data: s['sleep_mode'] = not s.get('sleep_mode', True)
            
        await write_db(db)
        buttons = generate_sleep_keyboard(acc_id, s)
        await event.edit(f"🌙 **অ্যাডভান্সড স্লিপ মোড কনফিগারেশন**\n(Region: BD Time / UTC+6)\n\nআপডেট করা হয়েছে!", buttons=buttons)

    elif data.startswith("tog_ghost_"):
        acc_id = data[data.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        s = db['users'][str(user_id)]['accounts'][acc_id]['settings']
        s['ghost_forward'] = not s.get('ghost_forward', True)
        await write_db(db)
        text = f"⚙️ **সেটিংস: {db['users'][str(user_id)]['accounts'][acc_id]['phone']}**"
        buttons = [
            [Button.inline(f"Ghost Forward: {'✅' if s.get('ghost_forward') else '❌'}", data=f"tog_ghost_{acc_id}".encode('utf-8'))],
            [Button.inline(f"Advanced Sleep Mode 🌙", data=f"sleepmenu_{acc_id}".encode('utf-8'))],
            [Button.inline("🔙 অ্যাকাউন্ট লিস্ট", data=b"user_settings")]
        ]
        await event.edit(text, buttons=buttons)

    # --- CAMPAIGN MANAGEMENT ---
    elif data == "manage_campaigns":
        accounts = db['users'][str(user_id)].get('accounts', {})
        if not accounts: return await event.answer("আগে অ্যাকাউন্ট লগইন করুন!", alert=True)
        text = "🚀 **ক্যাম্পেইন ম্যানেজমেন্ট**"
        buttons = [[Button.inline(f"🚀 {acc['phone']}", data=f"camp_{a_id}".encode('utf-8'))] for a_id, acc in accounts.items()]
        buttons.append([Button.inline("🔙 ড্যাশবোর্ড", data=b"user_dashboard")])
        await event.edit(text, buttons=buttons)

    elif data.startswith("camp_"):
        acc_id = data[data.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        text, buttons = get_campaign_panel(db, user_id, acc_id)
        await event.edit(text, buttons=buttons)

    # --- INLINE TIME SELECTOR ---
    elif data.startswith("timeopt_"):
        acc_id = data[data.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        text = "⏱️ **ইন্টারভাল সেটআপ (Inline Select)**\n\nমেসেজ পাঠানোর ইন্টারভাল সিলেক্ট করুন:"
        buttons = [
            [Button.inline("🤖 Safe Auto (অটো ক্যালকুলেট)", data=f"setinv_auto_{acc_id}".encode('utf-8'))],
            [Button.inline("5 Min", data=f"setinv_5_{acc_id}".encode('utf-8')), Button.inline("10 Min", data=f"setinv_10_{acc_id}".encode('utf-8'))],
            [Button.inline("30 Min", data=f"setinv_30_{acc_id}".encode('utf-8')), Button.inline("60 Min", data=f"setinv_60_{acc_id}".encode('utf-8'))],
            [Button.inline("✍️ Custom Type", data=f"settime_{acc_id}".encode('utf-8'))],
            [Button.inline("🔙 প্যানেল", data=f"camp_{acc_id}".encode('utf-8'))]
        ]
        await event.edit(text, buttons=buttons)

    elif data.startswith("setinv_"):
        parts = data.split("_")
        val = parts[1]
        acc_id = data[data.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        camp = db['users'][str(user_id)]['accounts'][acc_id]['campaign']
        
        if val == "auto":
            camp['custom_time'] = False
            camp['interval'] = max(1, int(len(camp['filtered_groups']) * 0.5))
        else:
            camp['custom_time'] = True
            camp['interval'] = int(val)
            
        await write_db(db)
        await event.answer(f"ইন্টারভাল আপডেট করা হয়েছে!", alert=True)
        text, buttons = get_campaign_panel(db, user_id, acc_id)
        await event.edit(text, buttons=buttons)

    # --- TASK MANAGER (Join & Extract) ---
    elif data.startswith("taskmgr_"):
        acc_id = data[data.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        buttons = [
            [Button.inline("📥 Add Task (Join Groups)", data=f"addtask_{acc_id}".encode('utf-8'))],
            [Button.inline("👁️ View Task (Join Status)", data=f"viewtask_{acc_id}".encode('utf-8'))],
            [Button.inline("📤 লিংক এক্সট্র্যাক্ট", data=f"extract_{acc_id}".encode('utf-8'))],
            [Button.inline("🔙 প্যানেল", data=f"camp_{acc_id}".encode('utf-8'))]
        ]
        await event.edit("📋 **টাস্ক ম্যানেজার**\n\nএখান থেকে গ্রুপ জয়েনিং এবং লিংক এক্সট্র্যাক্ট পরিচালনা করুন:", buttons=buttons)

    elif data.startswith("addtask_"):
        acc_id = data[data.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        user_states[real_user_id] = f"WAITING_FOR_JOIN_TASK_{acc_id}"
        await event.edit("📥 **অ্যাড টাস্ক (Join)**\n\nগ্রুপের লিংকগুলো টেক্সট আকারে (Space/Newline দিয়ে) দিন অথবা .json ফাইল আপলোড করুন:", buttons=[[Button.inline("❌ বাতিল", data=f"taskmgr_{acc_id}".encode('utf-8'))]])

    elif data.startswith("viewtask_"):
        acc_id = data[data.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        tasks = join_task_queue.get(acc_id, [])
        if not tasks: return await event.answer("কোনো রানিং বা পেন্ডিং টাস্ক নেই!", alert=True)
        
        text = "👁️ **জয়েন অ্যাকশন লিস্ট**\n\n"
        for i, t in enumerate(tasks[-15:]): 
            ico = "⏳" if t['status'] == 'waiting' else "🔄" if t['status'] == 'processing' else t['status'][-1]
            text += f"{i+1}. {ico} `{t['link'][:20]}...` - {t['status']}\n"
        
        await event.edit(text, buttons=[[Button.inline("🔄 রিফ্রেশ", data=f"viewtask_{acc_id}".encode('utf-8'))], [Button.inline("🔙 ব্যাক", data=f"taskmgr_{acc_id}".encode('utf-8'))]])

    # --- LIVE VIEW AUTOMATION ---
    elif data.startswith("liveview_"):
        acc_id = data[data.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        ls = live_automation_status.get(acc_id, {'success': [], 'processing': [], 'waiting': [], 'failed': []})
        
        text = "👁️ **লাইভ অটোমেশন টাস্ক**\n\n"
        text += "**✅ Success (Last 2):**\n" + ("\n".join([f"{i+1}. {x} ✅" for i, x in enumerate(ls['success'][-2:])]) if ls['success'] else "  None") + "\n\n"
        text += "**🔄 Processing (Max 4):**\n" + ("\n".join([f"{i+1}. {x.get('title', x) if isinstance(x, dict) else x} 🔄" for i, x in enumerate(ls['processing'][:4])]) if ls['processing'] else "  None") + "\n\n"
        text += "**⏳ Waiting (Next 4):**\n" + ("\n".join([f"{i+1}. {x.get('title', x) if isinstance(x, dict) else x} ⏳" for i, x in enumerate(ls['waiting'][:4])]) if ls['waiting'] else "  None")
        
        await event.edit(text, buttons=[[Button.inline("🔄 লাইভ রিফ্রেশ", data=f"liveview_{acc_id}".encode('utf-8'))], [Button.inline("🔙 প্যানেল", data=f"camp_{acc_id}".encode('utf-8'))]])

    # --- FILTERS & GROUP SETUP ---
    elif data.startswith("grpsetup_"):
        acc_id = data[data.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        text, buttons = get_group_setup_panel(db, user_id, acc_id)
        await event.edit(text, buttons=buttons)

    elif data.startswith("addflt_"):
        acc_id = data[data.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        user_states[real_user_id] = f"WAITING_FOR_FILTER_{acc_id}"
        await event.edit("➕ **ফিল্টার যোগ**\nযে শব্দ দিয়ে ফিল্টার করতে চান তা দিন (যেমন: buy):", buttons=[[Button.inline("❌ বাতিল", data=f"grpsetup_{acc_id}".encode('utf-8'))]])

    elif data.startswith("rmvflt_"):
        acc_id = data[data.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        camp = db['users'][str(user_id)]['accounts'][acc_id]['campaign']
        if not camp['filters']: return await event.answer("কোনো ফিল্টার নেই!", alert=True)
        
        buttons = [[Button.inline(f"❌ {f}", data=f"del_flt_{f}_{acc_id}".encode('utf-8'))] for f in camp['filters']]
        buttons.append([Button.inline("🔙 ব্যাক", data=f"grpsetup_{acc_id}".encode('utf-8'))])
        await event.edit("➖ **রিমুভ ফিল্টার**\nযেটি রিমুভ করতে চান সেটিতে ক্লিক করুন:", buttons=buttons)

    elif data.startswith("del_flt_"):
        acc_id = data[data.find("acc_"):]
        flt_val = data[len("del_flt_"):data.find("_acc_")]
        ensure_account_structure(db, user_id, acc_id)
        camp = db['users'][str(user_id)]['accounts'][acc_id]['campaign']
        
        if flt_val in camp['filters']: camp['filters'].remove(flt_val)
        
        if camp['filters']:
            camp['filtered_groups'] = [g for g in camp['target_groups'] if any(f.lower() in g['title'].lower() for f in camp['filters'])]
        else:
            camp['filtered_groups'] = camp['target_groups']
            
        camp['target_count'] = len(camp['filtered_groups'])
        if not camp.get('custom_time'): camp['interval'] = max(1, int(len(camp['filtered_groups']) * 0.5))
        await write_db(db)
        
        await event.answer(f"ফিল্টার {flt_val} রিমুভড!", alert=True)
        text, buttons = get_group_setup_panel(db, user_id, acc_id)
        await event.edit(text, buttons=buttons)

    elif data.startswith("viewgrp_"):
        acc_id = data[data.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        camp = db['users'][str(user_id)]['accounts'][acc_id]['campaign']
        targets = camp.get('filtered_groups', [])
        
        if not targets: return await event.answer("কোনো টার্গেট গ্রুপ নেই!", alert=True)
            
        text = "📋 **আপনার ফিল্টার্ড টার্গেট লিস্ট:**\n\n"
        for i, grp in enumerate(targets[:30]): 
            title = grp.get('title', 'Unknown Group') if isinstance(grp, dict) else f"ID: {grp}"
            text += f"{i+1}. {title}\n"
        if len(targets) > 30: text += f"\n*...এবং আরও {len(targets) - 30} টি গ্রুপ।*\n"
            
        buttons = [[Button.inline("🔙 ব্যাক", data=f"grpsetup_{acc_id}".encode('utf-8'))]]
        await event.edit(text, buttons=buttons)

    elif data.startswith("fetchgrp_"):
        acc_id = data[data.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        acc = db['users'][str(user_id)]['accounts'][acc_id]
        
        await show_digital_loading(event, "অ্যাডভান্সড গ্রুপ স্ক্যান করা হচ্ছে...")
        
        client = TelegramClient(StringSession(acc['session_string']), API_ID, API_HASH)
        await client.connect()
        groups = []
        async for dialog in client.iter_dialogs():
            if dialog.is_group: groups.append({"id": dialog.id, "title": dialog.title})
        await client.disconnect()
        
        camp = acc['campaign']
        camp['target_groups'] = groups
        
        if camp['filters']:
            camp['filtered_groups'] = [g for g in groups if any(f.lower() in g['title'].lower() for f in camp['filters'])]
        else:
            camp['filtered_groups'] = groups
            
        camp['target_count'] = len(camp['filtered_groups'])
        if not camp.get('custom_time'): camp['interval'] = max(1, int(len(camp['filtered_groups']) * 0.5))
        
        await write_db(db)
        await event.answer(f"✅ {len(groups)} গ্রুপ স্ক্যান হয়েছে! ফিল্টার্ড টার্গেট: {len(camp['filtered_groups'])}", alert=True)
        text, buttons = get_group_setup_panel(db, user_id, acc_id)
        await event.edit(text, buttons=buttons)

    # --- EXTRACT LINKS ---
    elif data.startswith("extract_"):
        acc_id = data[data.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        user_states[real_user_id] = f"WAITING_FOR_EXTRACT_{acc_id}"
        msg = "📤 **গ্রুপ লিংক এক্সট্র্যাক্ট**\n\nযে কিওয়ার্ড দিয়ে ফিল্টার করতে চান তা দিন (একাধিক হলে কমা দিয়ে লিখুন, যেমন: `buy, sell`)।\nসব গ্রুপের লিংক চাইলে `all` লিখে সেন্ড করুন:"
        await event.edit(msg, buttons=[[Button.inline("❌ বাতিল করুন", data=f"taskmgr_{acc_id}".encode('utf-8'))]])

    elif data.startswith("extfmt_"):
        parts = data.split('_')
        fmt = parts[1]
        acc_id = data[data.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        filters = user_temp_data.get(real_user_id, {}).get("filters", [])
        
        await show_digital_loading(event, "লিংক এক্সট্র্যাক্ট করা হচ্ছে...")
        acc = db['users'][str(user_id)]['accounts'][acc_id]
        client = TelegramClient(StringSession(acc['session_string']), API_ID, API_HASH)
        await client.connect()
        links = []
        try:
            async for dialog in client.iter_dialogs():
                if dialog.is_group or dialog.is_channel:
                    uname = getattr(dialog.entity, 'username', None)
                    if uname:
                        link = f"https://t.me/{uname}"
                        if not filters: links.append(link)
                        else:
                            if any(f in uname.lower() for f in filters): links.append(link)
        except Exception: pass
        await client.disconnect()

        if not links:
            return await event.edit("⚠️ কোনো লিংক পাওয়া যায়নি!", buttons=[[Button.inline("🔙 প্যানেলে যান", data=f"taskmgr_{acc_id}".encode('utf-8'))]])

        if fmt == 'text':
            out = "\n".join(links)
            if len(out) > 4000: fmt = 'json' 
            else: return await event.edit(f"✅ **এক্সট্র্যাক্ট করা লিংক ({len(links)} টি):**\n\n{out}", buttons=[[Button.inline("🔙 প্যানেলে যান", data=f"taskmgr_{acc_id}".encode('utf-8'))]])

        if fmt == 'json':
            file_name = f"extracted_links_{int(time.time())}.json"
            with open(file_name, 'w') as f: json.dump(links, f, indent=4)
            await bot.send_file(real_user_id, file_name, caption=f"✅ {len(links)} টি লিংক এক্সট্র্যাক্ট করা হয়েছে।")
            os.remove(file_name)
            await event.edit("✅ ফাইল পাঠানো হয়েছে!", buttons=[[Button.inline("🔙 প্যানেলে যান", data=f"taskmgr_{acc_id}".encode('utf-8'))]])

    elif data.startswith("setsource_"):
        acc_id = data[data.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        user_states[real_user_id] = f"WAITING_FOR_SOURCE_{acc_id}"
        msg = "🔗 **সোর্স চ্যানেল সেটআপ**\n\nপ্রাইভেট চ্যানেলের ক্ষেত্রে ওই চ্যানেল থেকে **যেকোনো একটি মেসেজ এই বটে ফরোয়ার্ড করুন**।\nঅথবা, সরাসরি চ্যানেলের Chat ID (যেমন: `-100...`) বা ইউজারনেম দিন (যেমন @mychannel):"
        await event.edit(msg, buttons=[[Button.inline("❌ বাতিল করুন", data=f"camp_{acc_id}".encode('utf-8'))]])

    elif data.startswith("settime_"):
        acc_id = data[data.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        user_states[real_user_id] = f"WAITING_FOR_TIME_{acc_id}"
        msg = "⏱️ **মিনিট দিন (যেমন 5):**"
        await event.edit(msg, buttons=[[Button.inline("❌ বাতিল করুন", data=f"timeopt_{acc_id}".encode('utf-8'))]])

    elif data.startswith("toggcamp_"):
        acc_id = data[data.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        camp = db['users'][str(user_id)]['accounts'][acc_id]['campaign']
        
        if camp.get('status') == "Stopped":
            if not camp.get('filtered_groups', []) or camp.get('source') in ["None", "Set Not Yet"]:
                return await event.answer("⚠️ আগে গ্রুপ ডিটেক্ট এবং সোর্স দিন!", alert=True)
            camp['status'] = "Running"
            camp['last_run'] = 0 
            await event.answer("🚀 স্টার্ট করা হয়েছে!", alert=True)
        else:
            camp['status'] = "Stopped"
            await event.answer("⏹️ স্টপ করা হয়েছে!", alert=True)
        
        await write_db(db)
        text, buttons = get_campaign_panel(db, user_id, acc_id)
        await event.edit(text, buttons=buttons)

    elif data == "cancel_action":
        if real_user_id in user_states: del user_states[real_user_id]
        if user_id in pending_logins:
            await pending_logins[user_id]["client"].disconnect()
            del pending_logins[user_id]
        text, buttons = await get_main_menu(user_id, is_admin, is_stealth)
        await event.edit("❌ **অ্যাকশন বাতিল।**\n\n" + text, buttons=buttons)

    elif data == "main_menu":
        if real_user_id in user_states: del user_states[real_user_id]
        text, buttons = await get_main_menu(user_id, is_admin, is_stealth)
        await event.edit(text, buttons=buttons)

# ==========================================
# 6. MESSAGE HANDLER (Inputs)
# ==========================================
@bot.on(events.NewMessage())
async def message_handler(event):
    if not event.is_private or event.text.startswith('/'): return
    real_user_id = event.sender_id
    
    try: await event.delete() 
    except Exception: pass
    
    if real_user_id not in user_states: return
    state = user_states[real_user_id]
    user_id = admin_impersonating.get(real_user_id, real_user_id) 
    db = await read_db()

    # --- FILTER ADDITION ---
    if state.startswith("WAITING_FOR_FILTER_"):
        acc_id = state[state.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        new_filter = event.text.strip().lower()
        camp = db['users'][str(user_id)]['accounts'][acc_id]['campaign']
        if new_filter not in camp['filters']: camp['filters'].append(new_filter)
        
        camp['filtered_groups'] = [g for g in camp['target_groups'] if any(f.lower() in g['title'].lower() for f in camp['filters'])]
        if not camp.get('custom_time'): camp['interval'] = max(1, int(len(camp['filtered_groups']) * 0.5))
        
        await write_db(db)
        del user_states[real_user_id]
        await edit_or_respond(real_user_id, f"✅ ফিল্টার `{new_filter}` যুক্ত হয়েছে!", [[Button.inline("🔙 ব্যাক", data=f"grpsetup_{acc_id}".encode('utf-8'))]])

    # --- EXTRACT LINKS ---
    elif state.startswith("WAITING_FOR_EXTRACT_"):
        acc_id = state[state.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        text_val = event.text.strip().lower()
        if text_val == 'all': filters = []
        else: filters = [x.strip() for x in text_val.split(',') if x.strip()]
        user_temp_data[real_user_id] = {"filters": filters}
        del user_states[real_user_id]

        buttons = [
            [Button.inline("📝 Text (মেসেজ)", data=f"extfmt_text_{acc_id}".encode('utf-8')), Button.inline("📁 JSON (ফাইল)", data=f"extfmt_json_{acc_id}".encode('utf-8'))],
            [Button.inline("🔙 বাতিল করুন", data=f"taskmgr_{acc_id}".encode('utf-8'))]
        ]
        await edit_or_respond(real_user_id, f"✅ ফিল্টার সেভ হয়েছে: `{text_val}`\n\nআপনি কোন ফরম্যাটে এক্সট্র্যাক্ট করা লিংকগুলো পেতে চান?", buttons)

    # --- JOIN TASK QUEUE IMPORTER ---
    elif state.startswith("WAITING_FOR_JOIN_TASK_"):
        acc_id = state[state.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        links = []
        if event.message.media and hasattr(event.message.media, 'document'):
            path = await bot.download_media(event.message)
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, list): links = data
            except: pass
            finally:
                if os.path.exists(path): os.remove(path)
        else:
            links = re.split(r'[\s\n,]+', event.text.strip())

        links = [l.strip() for l in links if l.strip()]
        if not links: return await edit_or_respond(real_user_id, "⚠️ লিংক পাওয়া যায়নি!", [[Button.inline("🔙 ব্যাক", data=f"taskmgr_{acc_id}".encode('utf-8'))]])

        for link in links: join_task_queue[acc_id].append({'link': link, 'status': 'waiting'})
        del user_states[real_user_id]
        await edit_or_respond(real_user_id, f"✅ {len(links)} টি লিংক টাস্ক ম্যানেজারে যুক্ত হয়েছে! ব্যাকগ্রাউন্ডে জয়েনিং শুরু হবে।", [[Button.inline("👁️ ভিউ টাস্ক", data=f"viewtask_{acc_id}".encode('utf-8')), Button.inline("🔙 ব্যাক", data=f"taskmgr_{acc_id}".encode('utf-8'))]])

    # --- ADMIN STATES ---
    elif state == "WAITING_FOR_GLOBAL_JOIN":
        link = event.text.strip()
        wait_msg = await event.respond("⏳ গ্লোবাল জয়েন প্রসেস শুরু হয়েছে... এটি কিছুক্ষণ সময় নিতে পারে। (Syncing...)")
        del user_states[real_user_id]
        success, failed = 0, 0
        for uid, udata in db.get('users', {}).items():
            for acc_id, acc in udata.get('accounts', {}).items():
                try:
                    client = TelegramClient(StringSession(acc['session_string']), API_ID, API_HASH)
                    await client.connect()
                    await process_join_link(client, link)
                    success += 1
                    await client.disconnect()
                except Exception: failed += 1
        await wait_msg.delete()
        await edit_or_respond(real_user_id, f"✅ **গ্লোবাল জয়েন সম্পন্ন!**\nসাফল্য: {success} টি অ্যাকাউন্ট\nব্যর্থ: {failed} টি অ্যাকাউন্ট", [[Button.inline("🔙 অ্যাডমিন প্যানেল", data=b"admin_panel")]])

    elif state == "WAITING_FOR_SUPPORT_USER":
        db['system']['support_user'] = event.text.strip()
        await write_db(db)
        del user_states[real_user_id]
        await edit_or_respond(real_user_id, f"✅ সাপোর্ট ইউজারনেম সেভ করা হয়েছে!", [[Button.inline("🔙 অ্যাডমিন প্যানেল", data=b"admin_panel")]])

    elif state == "WAITING_FOR_BROADCAST":
        del user_states[real_user_id]
        msg = event.message
        count, failed = 0, 0
        wait = await event.respond("📢 ব্রডকাস্ট পাঠানো শুরু হয়েছে...")
        for uid in db.get('users', {}).keys():
            try:
                await bot.send_message(int(uid), msg)
                count += 1
                await asyncio.sleep(0.5)
            except Exception: failed += 1
        await wait.delete()
        await edit_or_respond(real_user_id, f"✅ **ব্রডকাস্ট সম্পন্ন!**\nসাফল্য: {count} জন\nব্যর্থ: {failed} জন", [[Button.inline("🔙 অ্যাডমিন প্যানেল", data=b"admin_panel")]])

    # --- LOGIN LOGIC ---
    elif state == "WAITING_FOR_PHONE":
        phone = event.text.strip()
        if not phone.startswith('+') or len(phone) < 10: return await edit_or_respond(real_user_id, "⚠️ সঠিক নাম্বার দিন (+ সহ)", [[Button.inline("❌ বাতিল করুন", data=b"cancel_action")]])
            
        wait_msg = await event.respond("⏳ রিকোয়েস্ট পাঠানো হচ্ছে...")
        user_client = TelegramClient(StringSession(), API_ID, API_HASH)
        await user_client.connect()
        try:
            send_code = await user_client.send_code_request(phone)
            pending_logins[user_id] = {"client": user_client, "phone": phone, "hash": send_code.phone_code_hash}
            user_states[real_user_id] = "WAITING_FOR_OTP"
            await wait_msg.delete()
            await edit_or_respond(real_user_id, f"✅ OTP কোড পাঠানো হয়েছে। কোডটি দিন:", [[Button.inline("❌ বাতিল করুন", data=b"cancel_action")]])
        except Exception as e:
            await wait_msg.delete()
            await edit_or_respond(real_user_id, f"❌ এরর: {e}", [[Button.inline("❌ বাতিল করুন", data=b"cancel_action")]])
            await user_client.disconnect()
            del user_states[real_user_id]

    elif state == "WAITING_FOR_OTP":
        raw_input = event.text.strip()
        formatted_otp = '-'.join(list(raw_input.replace('-', '').replace(' ', '')))
        login_data = pending_logins.get(user_id)
        if not login_data:
            del user_states[real_user_id]
            return await edit_or_respond(real_user_id, "⚠️ সেশন টাইমআউট!", [[Button.inline("🔙 প্রধান মেনু", data=b"main_menu")]])
            
        user_client = login_data["client"]
        wait_msg = await event.respond("⏳ যাচাই করা হচ্ছে...")
        try:
            await user_client.sign_in(phone=login_data["phone"], code=formatted_otp, phone_code_hash=login_data["hash"])
            session_string = user_client.session.save()
            await save_account_to_db(user_id, login_data["phone"], session_string) 
            await wait_msg.delete()
            await edit_or_respond(real_user_id, "🎉 লগইন সফল!", [[Button.inline("🔙 ড্যাশবোর্ড", data=b"user_dashboard")]])
            await user_client.disconnect()
            del user_states[real_user_id]
            del pending_logins[user_id]
        except SessionPasswordNeededError:
            user_states[real_user_id] = "WAITING_FOR_PASSWORD"
            await wait_msg.delete()
            await edit_or_respond(real_user_id, "🔐 2-Step Verification অন আছে! পাসওয়ার্ড দিন:", [[Button.inline("❌ বাতিল করুন", data=b"cancel_action")]])
        except Exception as e:
            await wait_msg.delete()
            await edit_or_respond(real_user_id, f"❌ এরর: {e}", [[Button.inline("❌ বাতিল করুন", data=b"cancel_action")]])
            await user_client.disconnect()
            del user_states[real_user_id]
            del pending_logins[user_id]

    elif state == "WAITING_FOR_PASSWORD":
        password = event.text.strip()
        login_data = pending_logins.get(user_id)
        user_client = login_data["client"]
        wait_msg = await event.respond("⏳ যাচাই করা হচ্ছে...")
        try:
            await user_client.sign_in(password=password)
            session_string = user_client.session.save()
            await save_account_to_db(user_id, login_data["phone"], session_string, password)
            await wait_msg.delete()
            await edit_or_respond(real_user_id, "🎉 লগইন সফল!", [[Button.inline("🔙 ড্যাশবোর্ড", data=b"user_dashboard")]])
            await user_client.disconnect()
            del user_states[real_user_id]
            del pending_logins[user_id]
        except Exception as e:
            await wait_msg.delete()
            await edit_or_respond(real_user_id, f"❌ পাসওয়ার্ড ভুল: {e}", [[Button.inline("❌ বাতিল করুন", data=b"cancel_action")]])
            await user_client.disconnect()
            del user_states[real_user_id]
            del pending_logins[user_id]

    # --- CAMPAIGN CONFIGURATIONS ---
    elif state.startswith("WAITING_FOR_SOURCE_"):
        acc_id = state[state.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        source = None
        
        if event.forward and event.forward.chat_id:
            source = event.forward.chat_id
        else:
            text_val = event.text.strip()
            if text_val.startswith('https://t.me/'):
                text_val = text_val.replace('https://t.me/', '')
                if not text_val.startswith('+') and not text_val.startswith('joinchat/'): text_val = '@' + text_val
            if text_val.lstrip('-').isdigit(): source = int(text_val)
            else: source = text_val
                
        wait_msg = await event.respond("⏳ সোর্স চ্যানেল চেক করা হচ্ছে (অ্যাকাউন্ট সিঙ্ক)...")
        try:
            session_string = db['users'][str(user_id)]['accounts'][acc_id]['session_string']
            user_client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
            await user_client.connect()
            try:
                entity = await user_client.get_entity(source)
                channel_title = getattr(entity, 'title', str(source))
                
                db['users'][str(user_id)]['accounts'][acc_id]['campaign']['source'] = source
                db['users'][str(user_id)]['accounts'][acc_id]['campaign']['source_title'] = channel_title
                await write_db(db)
                
                await wait_msg.delete()
                del user_states[real_user_id]
                await edit_or_respond(real_user_id, f"✅ সোর্স চ্যানেল `{channel_title}` সফলভাবে সিঙ্ক ও সেভ করা হয়েছে!", [[Button.inline("🔙 প্যানেলে যান", data=f"camp_{acc_id}".encode('utf-8'))]])
            except ValueError:
                 await wait_msg.delete()
                 await edit_or_respond(real_user_id, f"❌ এরর: আপনার লগইন করা অ্যাকাউন্ট এই চ্যানেলে জয়েন করা নেই বা ID/Username ভুল।", [[Button.inline("🔙 প্যানেলে যান", data=f"camp_{acc_id}".encode('utf-8'))]])
            except Exception as e:
                await wait_msg.delete()
                await edit_or_respond(real_user_id, f"❌ এরর: {e}", [[Button.inline("🔙 প্যানেলে যান", data=f"camp_{acc_id}".encode('utf-8'))]])
            finally:
                await user_client.disconnect()
        except Exception as e:
            await wait_msg.delete()
            await edit_or_respond(real_user_id, f"❌ সিস্টেম এরর: {e}")

    elif state.startswith("WAITING_FOR_TIME_"):
        acc_id = state[state.find("acc_"):]
        ensure_account_structure(db, user_id, acc_id)
        try: interval = int(event.text.strip())
        except ValueError: return await edit_or_respond(real_user_id, "⚠️ শুধুমাত্র সংখ্যা দিন (যেমন: 5)", [[Button.inline("❌ বাতিল করুন", data=f"timeopt_{acc_id}".encode('utf-8'))]])
            
        try:
            db['users'][str(user_id)]['accounts'][acc_id]['campaign']['interval'] = interval
            db['users'][str(user_id)]['accounts'][acc_id]['campaign']['custom_time'] = True
            await write_db(db)
            del user_states[real_user_id]
            await edit_or_respond(real_user_id, f"✅ ইন্টারভাল `{interval}` মিনিট সেট করা হয়েছে!", [[Button.inline("🔙 প্যানেলে যান", data=f"camp_{acc_id}".encode('utf-8'))]])
        except Exception as e:
            await edit_or_respond(real_user_id, f"❌ এরর: {e}", [[Button.inline("🔙 প্যানেলে যান", data=f"camp_{acc_id}".encode('utf-8'))]])

# ==========================================
# 7. SYSTEM STARTUP
# ==========================================
async def main():
    await init_db()
    print("✅ System Core and Database Online!")
    await bot.start(bot_token=BOT_TOKEN)
    print("🤖 Bot UI is now running!")
    asyncio.create_task(automation_loop())
    asyncio.create_task(background_join_worker()) 
    asyncio.create_task(daily_cleanup_worker()) 
    await bot.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())