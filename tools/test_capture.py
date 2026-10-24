import sys
sys.path.insert(0, ".")
from app.vision.capture import grab, foreground_info, guess_game_name

shot = grab(max_width=1280)
print("title:", shot.title[:40])
print("process:", shot.process)
print("game:", shot.game_name)
print("size:", shot.width, "x", shot.height, "jpeg:", len(shot.jpeg) // 1024, "KB")
print("magic ok:", shot.jpeg[:3] == b"\xff\xd8\xff")
