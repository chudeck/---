# 파일 1: main.py
import discord
from discord.ext import commands
from flask import Flask, render_template, request, jsonify
import asyncio
import threading
import uuid
import json
import os
import requests
import time
from datetime import datetime
import sqlite3

# 데이터베이스 초기화
def init_db():
    conn = sqlite3.connect('minecraft_auth.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS auth_sessions (
        session_id TEXT PRIMARY KEY,
        discord_user_id TEXT,
        created_at TIMESTAMP,
        used BOOLEAN DEFAULT FALSE
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS authenticated_users (
        discord_user_id TEXT PRIMARY KEY,
        minecraft_uuid TEXT,
        minecraft_username TEXT,
        ip_address TEXT,
        authenticated_at TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS server_settings (
        guild_id TEXT,
        setting_type TEXT,
        setting_value TEXT,
        PRIMARY KEY (guild_id, setting_type)
    )''')
    
    conn.commit()
    conn.close()

init_db()

# Discord Bot 설정
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='/', intents=intents)

# Flask 웹서버
app = Flask(__name__)

# 기본 URL 설정 (나중에 Railway URL로 변경)
BASE_URL = os.getenv('BASE_URL', 'https://your-app-name.up.railway.app')

class AuthButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label='마인크래프트 인증', style=discord.ButtonStyle.primary, emoji='⛏️')
    async def minecraft_auth(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 인증 차단 역할 체크
        blocked_role = get_server_setting(interaction.guild.id, 'blocked_role')
        if blocked_role:
            role = interaction.guild.get_role(int(blocked_role))
            if role in interaction.user.roles:
                await interaction.response.send_message("❌ 인증이 차단된 사용자입니다.", ephemeral=True)
                return
        
        # 이미 인증된 사용자 체크
        conn = sqlite3.connect('minecraft_auth.db')
        c = conn.cursor()
        c.execute("SELECT * FROM authenticated_users WHERE discord_user_id = ?", (str(interaction.user.id),))
        if c.fetchone():
            await interaction.response.send_message("✅ 이미 인증이 완료된 사용자입니다.", ephemeral=True)
            conn.close()
            return
        conn.close()
        
        # 새로운 인증 세션 생성
        session_id = str(uuid.uuid4())
        
        conn = sqlite3.connect('minecraft_auth.db')
        c = conn.cursor()
        c.execute("INSERT INTO auth_sessions (session_id, discord_user_id, created_at) VALUES (?, ?, ?)",
                 (session_id, str(interaction.user.id), datetime.now()))
        conn.commit()
        conn.close()
        
        auth_url = f"{BASE_URL}/minecraftauth/checknickname/{session_id}"
        
        embed = discord.Embed(
            title="🔗 마인크래프트 인증 링크",
            description=f"아래 링크를 클릭하여 인증을 완료해주세요!\n\n[**인증하러 가기**]({auth_url})",
            color=0x00ff00
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @discord.ui.button(label='닉네임 변경', style=discord.ButtonStyle.secondary, emoji='✏️')
    async def change_nickname(self, interaction: discord.Interaction, button: discord.ui.Button):
        conn = sqlite3.connect('minecraft_auth.db')
        c = conn.cursor()
        c.execute("SELECT * FROM authenticated_users WHERE discord_user_id = ?", (str(interaction.user.id),))
        user_data = c.fetchone()
        conn.close()
        
        if not user_data:
            await interaction.response.send_message("❌ 인증이 완료되지 않은 사용자입니다.", ephemeral=True)
            return
        
        session_id = str(uuid.uuid4())
        
        conn = sqlite3.connect('minecraft_auth.db')
        c = conn.cursor()
        c.execute("INSERT INTO auth_sessions (session_id, discord_user_id, created_at) VALUES (?, ?, ?)",
                 (session_id, str(interaction.user.id), datetime.now()))
        conn.commit()
        conn.close()
        
        change_url = f"{BASE_URL}/minecraftauth/checknickname/{session_id}?type=change"
        
        embed = discord.Embed(
            title="✏️ 닉네임 변경 링크",
            description=f"아래 링크를 클릭하여 닉네임을 변경해주세요!\n\n[**닉네임 변경하러 가기**]({change_url})",
            color=0xffaa00
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

def get_server_setting(guild_id, setting_type):
    conn = sqlite3.connect('minecraft_auth.db')
    c = conn.cursor()
    c.execute("SELECT setting_value FROM server_settings WHERE guild_id = ? AND setting_type = ?",
             (str(guild_id), setting_type))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def set_server_setting(guild_id, setting_type, setting_value):
    conn = sqlite3.connect('minecraft_auth.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO server_settings (guild_id, setting_type, setting_value) VALUES (?, ?, ?)",
             (str(guild_id), setting_type, str(setting_value)))
    conn.commit()
    conn.close()

@bot.event
async def on_ready():
    print(f'{bot.user} 봇이 온라인 상태입니다!')
    bot.add_view(AuthButton())

@bot.command(name='인증메뉴')
@commands.has_permissions(administrator=True)
async def auth_menu(ctx):
    embed = discord.Embed(
        title="🎮 마인크래프트 서버 인증",
        description="마인크래프트 인증을 하려면 아래 **인증하기** 버튼을 눌러 인증을 완료해주세요!",
        color=0x00ff00
    )
    
    view = AuthButton()
    await ctx.send(embed=embed, view=view)

@bot.command(name='인증설정')
@commands.has_permissions(administrator=True)
async def auth_settings(ctx, setting_type: str, target=None):
    if setting_type == "로그채널":
        if target is None:
            await ctx.send("❌ 로그 채널을 멘션해주세요.")
            return
        
        channel_id = target.replace('<#', '').replace('>', '')
        channel = bot.get_channel(int(channel_id))
        
        if not channel:
            await ctx.send("❌ 유효하지 않은 채널입니다.")
            return
        
        set_server_setting(ctx.guild.id, 'log_channel', channel_id)
        await ctx.send(f"✅ 로그 채널이 {channel.mention}으로 설정되었습니다.")

def get_minecraft_uuid(username):
    try:
        response = requests.get(f"https://api.mojang.com/users/profiles/minecraft/{username}")
        if response.status_code == 200:
            data = response.json()
            return data['id'], data['name']
        return None, None
    except:
        return None, None

@app.route('/')
def index():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>마인크래프트 인증 시스템</title>
        <meta charset="utf-8">
    </head>
    <body>
        <h1>마인크래프트 디스코드 인증 시스템</h1>
        <p>이 사이트는 마인크래프트 서버 인증을 위한 사이트입니다.</p>
    </body>
    </html>
    '''

@app.route('/minecraftauth/checknickname/<session_id>')
def auth_page(session_id):
    conn = sqlite3.connect('minecraft_auth.db')
    c = conn.cursor()
    c.execute("SELECT discord_user_id, used FROM auth_sessions WHERE session_id = ?", (session_id,))
    session_data = c.fetchone()
    conn.close()
    
    if not session_data:
        return '<h1>❌ 유효하지 않은 인증 링크</h1>'
    
    auth_type = request.args.get('type', 'auth')
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>마인크래프트 인증</title>
        <meta charset="utf-8">
        <style>
            body {{ font-family: Arial, sans-serif; text-align: center; padding: 50px; }}
            input {{ padding: 10px; margin: 10px; font-size: 16px; }}
            button {{ padding: 10px 20px; font-size: 16px; background: #007bff; color: white; border: none; cursor: pointer; }}
        </style>
    </head>
    <body>
        <h1>🎮 마인크래프트 {'닉네임 변경' if auth_type == 'change' else '인증'}</h1>
        <form id="authForm">
            <input type="text" id="username" placeholder="마인크래프트 닉네임" required>
            <br>
            <button type="submit">{'닉네임 변경' if auth_type == 'change' else '인증하기'}</button>
        </form>
        <div id="result"></div>
        
        <script>
            document.getElementById('authForm').addEventListener('submit', async function(e) {{
                e.preventDefault();
                const username = document.getElementById('username').value;
                
                const response = await fetch('/minecraftauth/verify/{session_id}', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ username: username, type: '{auth_type}' }})
                }});
                
                const data = await response.json();
                const resultDiv = document.getElementById('result');
                
                if (data.success) {{
                    resultDiv.innerHTML = '<h2>✅ 성공!</h2><p>디스코드를 확인해주세요!</p>';
                }} else {{
                    resultDiv.innerHTML = '<h2>❌ 실패</h2><p>' + data.error + '</p>';
                }}
            }});
        </script>
    </body>
    </html>
    '''

@app.route('/minecraftauth/verify/<session_id>', methods=['POST'])
def verify_auth(session_id):
    try:
        data = request.get_json()
        username = data.get('username')
        auth_type = data.get('type', 'auth')
        
        minecraft_uuid, minecraft_username = get_minecraft_uuid(username)
        
        if not minecraft_uuid:
            return jsonify({'success': False, 'error': '존재하지 않는 마인크래프트 닉네임입니다.'})
        
        conn = sqlite3.connect('minecraft_auth.db')
        c = conn.cursor()
        c.execute("SELECT discord_user_id FROM auth_sessions WHERE session_id = ?", (session_id,))
        session_data = c.fetchone()
        
        if not session_data:
            return jsonify({'success': False, 'error': '유효하지 않은 세션입니다.'})
        
        discord_user_id = session_data[0]
        
        if auth_type == 'change':
            c.execute("UPDATE authenticated_users SET minecraft_uuid = ?, minecraft_username = ? WHERE discord_user_id = ?",
                     (minecraft_uuid, minecraft_username, discord_user_id))
        else:
            c.execute("INSERT OR REPLACE INTO authenticated_users (discord_user_id, minecraft_uuid, minecraft_username, authenticated_at) VALUES (?, ?, ?, ?)",
                     (discord_user_id, minecraft_uuid, minecraft_username, datetime.now()))
        
        c.execute("UPDATE auth_sessions SET used = TRUE WHERE session_id = ?", (session_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    
    except Exception as e:
        return jsonify({'success': False, 'error': '서버 오류가 발생했습니다.'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    # Flask 서버를 별도 스레드에서 실행
    flask_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port))
    flask_thread.daemon = True
    flask_thread.start()
    
    # Discord 봇 실행
    bot.run(os.getenv('DISCORD_BOT_TOKEN'))
