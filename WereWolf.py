import random
import requests
import speech_recognition as sr

# API密钥和URL（你需要提供你的API密钥）
API_KEY = "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"
API_URL = "https://api.openai.com/v1/chat/completions"

# 设置请求头
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}"
}

# 初始化语音识别器
recognizer = sr.Recognizer()

def ai_query(prompt):
    """向AI API发送请求并返回AI的回答"""
    data = {
        "model": "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 100
    }
    try:
        response = requests.post(API_URL, json=data, headers=headers)
        response.raise_for_status()
        result = response.json()
        return result.get('choices', [{}])[0].get('message', {}).get('content', "AI无法给出合理的建议")
    except requests.exceptions.RequestException as e:
        print(f"请求错误: {e}")
        return "AI请求失败"


def recognize_speech_from_microphone():
    """通过麦克风进行语音识别"""
    with sr.Microphone() as source:
        print("请说话...")
        recognizer.adjust_for_ambient_noise(source)  # 适应环境噪声
        audio = recognizer.listen(source)

    try:
        print("正在识别...")
        speech_text = recognizer.recognize_google(audio, language='zh-CN')
        print(f"识别结果: {speech_text}")
        return speech_text
    except sr.UnknownValueError:
        print("无法识别语音")
        return None
    except sr.RequestError as e:
        print(f"无法连接到语音识别服务: {e}")
        return None


class Player:
    def __init__(self, name, role=None):
        self.name = name
        self.role = role
        self.is_alive = True
        self.check_result = None  # 记录预言家的查验结果
    
    def __str__(self):
        return f"{self.name} ({self.role}) - {'存活' if self.is_alive else '死亡'}"

class Game:
    def __init__(self, players):
        self.players = players
        self.human_player = None
        self.round = 0
        self.winner = None
        self.prophet_checked_player = None  # 存储预言家查验的玩家
        self.death_this_night = None  # 记录昨晚死亡的玩家

    def start_game(self):
        self.assign_roles()
        self.announce_human_role()  # 告诉真人玩家自己的身份
        self.print_players()
        input("按 Enter 键开始游戏...")  # 等待玩家开始游戏
        while not self.is_game_over():
            self.round += 1
            print(f"\n--- 第 {self.round} 轮 ---")
            self.night_phase()
            input("按 Enter 键继续到白天阶段...")  # 夜晚后等待玩家输入，进入白天
            if self.is_game_over():
                break
            self.day_phase()

        self.declare_winner()

    def assign_roles(self):
        """随机分配身份"""
        roles = ['平民', '平民', '平民', '狼人', '狼人', '狼人', '女巫', '预言家', '猎人']
        random.shuffle(roles)

        for i, player in enumerate(self.players):
            player.role = roles[i]
        
        self.human_player = self.players[0]  # 默认真人玩家是第一个玩家

    def announce_human_role(self):
        """裁判告诉真人玩家他的身份"""
        print(f"\n📢【裁判公告】真人玩家 {self.human_player.name}，你的身份是【{self.human_player.role}】。\n")

    def print_players(self):
        """打印所有玩家信息"""
        for player in self.players:
            print(player)

    def night_phase(self):
        print("\n🌙 夜晚阶段")
        self.werewolf_action()
        self.prophet_action()
        self.witch_action()
        self.hunter_action()

    def werewolf_action(self):
        """狼人选择目标"""
        print("狼人行动：")
        werewolves = [p for p in self.players if p.role == '狼人' and p.is_alive]
        
        # 如果狼人是AI，狼人决定杀谁但不打印
        if all(isinstance(w, Player) and w != self.human_player for w in werewolves):
            target = self.ai_decision(self.players, exclude=werewolves)
            target.is_alive = False
            self.death_this_night = target  # 记录昨晚死亡的玩家
        else:
            # 如果真人是狼人，先告诉他队友
            if self.human_player.role == '狼人':
                teammates = [p for p in werewolves if p != self.human_player]
                teammate_names = [teammate.name for teammate in teammates]
                print(f"【狼人队友】你有 {', '.join(teammate_names)} 作为队友。")

                input("按 Enter 键继续，决定今晚要杀的玩家...")
                # 让真人输入要杀的目标编号
                print("请告诉我你要杀的目标（输入玩家编号）：")
                target_index = int(input("输入编号：")) - 1
                target = self.players[target_index]
                print(f"你决定杀害 {target.name}")
                target.is_alive = False
                self.death_this_night = target  # 记录昨晚死亡的玩家
            else:
                target = self.ai_decision(self.players, exclude=werewolves)
                print(f"狼人决定杀害 {target.name}。")
                target.is_alive = False
                self.death_this_night = target  # 记录昨晚死亡的玩家

    def prophet_action(self):
        """预言家查验身份"""
        print("预言家行动：")
        prophet = next((p for p in self.players if p.role == '预言家' and p.is_alive), None)
        if prophet:
            target = self.ai_decision(self.players, exclude=[prophet])
            self.prophet_checked_player = target
            target_role = target.role
            
            # 如果预言家是AI，查验结果不显示
            if isinstance(prophet, Player) and prophet.name == self.human_player.name:
                # 只有真人玩家会看到查验结果
                print(f"预言家查验了 {target.name}，身份是：{target_role}")
                # 预言家的查验结果告诉所有玩家
                self.prophet_check_result(target.name, target_role)

    def prophet_check_result(self, player_name, player_role):
        """将预言家查验结果告诉真人玩家"""
        if self.human_player.role == '预言家':
            print(f"📢 预言家告诉你：{player_name} 的身份是 {player_role}。\n")

    def witch_action(self):
        """女巫是否使用解药或毒药"""
        print("女巫行动：")
        witch = next((p for p in self.players if p.role == '女巫' and p.is_alive), None)
        if witch:
            if random.choice([True, False]):
                target = self.ai_decision(self.players, exclude=[witch])
                target.is_alive = False
                self.death_this_night = target  # 记录昨晚死亡的玩家

    def hunter_action(self):
        """猎人如果死亡，带走一个人"""
        hunter = next((p for p in self.players if p.role == '猎人' and not p.is_alive), None)
        if hunter:
            target = self.ai_decision(self.players, exclude=[hunter])
            print(f"猎人带走了 {target.name}。")
            target.is_alive = False
            self.death_this_night = target  # 记录昨晚死亡的玩家

    def day_phase(self):
        print("\n☀️ 白天阶段")
        self.announce_daylight()
        self.speaking_phase()
        input("按 Enter 键继续到投票环节...")  # 发言阶段后等待玩家输入，进入投票
        self.voting_phase()

    def announce_daylight(self):
        """裁判宣布天亮信息"""
        print("\n📢 天亮了！")
        if self.death_this_night:
            print(f"昨晚玩家 {self.death_this_night.name} 死亡。")
        else:
            print("昨晚是平安夜，没有玩家死亡。")
        self.death_this_night = None  # 重置为 None，准备下一轮

    def speaking_phase(self):
        print("\n📢 玩家开始发言")
        for player in self.players:
            if player.is_alive:
                if player == self.human_player:
                    print(f"{self.human_player.name}（真人玩家）：")
                    # 第一次按 Enter 开始录音
                    input("按 Enter 键开始录音...")
                    speech = recognize_speech_from_microphone()
                    # 第二次按 Enter 停止录音，继续游戏
                    input("按 Enter 键结束录音并继续...")  
                    if speech:
                        print(f"{self.human_player.name} 说：{speech}")
                    else:
                        print("没有听到有效的发言")
                else:
                    ai_speech = self.ai_speech(player)
                    print(f"{player.name}（AI玩家）发言：{ai_speech}")
                input("按 Enter 键继续...")  # 每个玩家发言后，暂停等待

    def voting_phase(self):
        print("\n📢 投票环节")
        votes = {}

        if self.human_player.is_alive:
            vote_target = recognize_speech_from_microphone()
            if vote_target:
                votes[vote_target] = votes.get(vote_target, 0) + 1
                print(f"{self.human_player.name} 投票给了 {vote_target}")

        for player in self.players:
            if player.is_alive and player != self.human_player:
                target = self.ai_decision(self.players, exclude=[player])
                votes[target.name] = votes.get(target.name, 0) + 1
                print(f"{player.name} 投票给了 {target.name}")

        max_votes = max(votes.values(), default=0)
        if list(votes.values()).count(max_votes) == 1:
            eliminated = max(votes, key=votes.get)
            eliminated_player = next(p for p in self.players if p.name == eliminated)
            eliminated_player.is_alive = False
            print(f"📢 {eliminated} 被公投淘汰！")
        else:
            print("📢 投票平局，没有玩家被淘汰。")

    def ai_speech(self, player):
        """AI通过API生成发言"""
        if player.role == '狼人':
            prompt = f"狼人杀游戏中，{player.name} 是狼人，请提供一个隐藏身份的发言，避免暴露自己。假装自己是平民或其他角色，表现得怀疑其他人。"
        else:
            prompt = f"狼人杀游戏中，{player.name} 是 {player.role}，请提供一段符合身份的发言。"

        ai_response = ai_query(prompt)
        return ai_response  # 返回AI生成的发言文本

    def ai_decision(self, players, exclude=[]):
        """AI通过API做决策"""
        prompt = f"狼人杀游戏中，存活玩家有: {', '.join([p.name for p in players if p.is_alive and p not in exclude])}。\n请做出最佳选择。"
        response = ai_query(prompt)
        target_name = response.strip()
        return next((p for p in players if p.name == target_name and p.is_alive), random.choice(players))

    def is_game_over(self):
        """检查游戏是否结束"""
        alive_werewolves = any(p.role == '狼人' and p.is_alive for p in self.players)
        alive_humans = any(p.role != '狼人' and p.is_alive for p in self.players)
        return not alive_werewolves or not alive_humans

    def declare_winner(self):
        """宣布胜利者"""
        print("狼人胜利！" if any(p.role == '狼人' and p.is_alive for p in self.players) else "人类胜利！")

# 初始化游戏
players = [Player(f"玩家{i+1}") for i in range(9)]
game = Game(players)
game.start_game()
