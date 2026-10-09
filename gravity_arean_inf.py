"""
Gravity Arena — an endless gravity-assist game prototype
Run with: python gravity_arena.py

Fly as far to the right as you can. The world generates itself as you go.

Controls:
  W / Up             thrust (uses fuel; first press launches the ship)
  A,D / Left,Right   rotate (free)
  S / Down           brake (weaker than thrust, burns less fuel)
  Space              start / pause
  R                  new world
  T                  retry the same world
  Q                  quit (on the game over screen)
"""

import math
import random
import sys
import tkinter as tk
from tkinter import ttk

WIDTH, HEIGHT = 900, 650
G = 600000.0          # gravitational constant (px^3 / s^2 per unit mass)
SHIP_THRUST = 210.0
BRAKE_DECEL = 90.0             # braking is weaker than thrust...
BRAKE_FUEL_RATE = 0.4          # ...and burns 40% as much fuel per second
DT = 1 / 60
SHIP_START = (100.0, HEIGHT / 2)
SHIP_RADIUS = 9
FUEL_SECONDS_PER_LEVEL = 0.4   # seconds of full thrust per fuel level
FUEL_MAX_LEVEL = 10            # top of the slider = unlimited fuel
CAMERA_LEAD = 0.4              # ship sits at this fraction of the screen width when scrolling
PX_PER_METER = 10.0
OUT_GRACE = 2.5                # seconds you may spend outside the playfield
EDGE_ZONE = 80                 # px from a deadly edge where the yellow glow starts
EDGE_SPAN = 140                # half-length (px) of the glow along the edge, centered on the rocket
EDGE_SEG = 14                  # segment size used to draw the glow
TRAIL_MAX = 10                 # number of trail dots
TRAIL_EVERY = 7                # frames between trail dots

COLORS = ["#4cc9f0", "#f4a261", "#b8c0ff", "#80ed99", "#ff70a6", "#ffd166", "#cdb4db", "#a0e7e5"]
STAR_COLORS = ["#dce7f5", "#dce7f5", "#9fc5ff", "#ffe9b0"]
# Real exoplanets (nothing from our own solar system)
EXOPLANETS = ["Proxima b", "Kepler-22b", "Kepler-452b", "Kepler-186f", "TRAPPIST-1e", "TRAPPIST-1f",
              "TRAPPIST-1d", "Gliese 667 Cc", "LHS 1140 b", "TOI-700 d", "Teegarden b", "K2-18 b",
              "HD 209458 b", "51 Pegasi b", "55 Cancri e", "WASP-12b", "GJ 1214 b", "Kepler-16b",
              "HD 189733 b", "Dimidium", "Draugr", "Poltergeist", "Phobetor", "Dagon"]
END_STATES = ("crashed", "escaped")


class Body:
    def __init__(self, x, y, radius, color, name="Planet"):
        self.x, self.y = float(x), float(y)
        self.radius, self.color, self.name = radius, color, name
        # Bigger planet = more mass = stronger gravity (mass scales with surface area).
        self.mass = (radius / 20.0) ** 2


class Drifter:
    """Something that drifts in a straight line through the view (world coordinates)."""
    radius_range = (8, 14)
    speed_range = (45, 95)
    sides = "RTB"

    def __init__(self, cam_x):
        self.spawn(cam_x, stagger=True)

    def spawn(self, cam_x, stagger=False):
        self.radius = random.randint(*self.radius_range)
        side = random.choice(self.sides)
        # With stagger, objects start far off-screen so they arrive at different times.
        margin = 40 + (random.uniform(0, 500) if stagger else random.uniform(0, 40))
        if side == "R":
            self.x, self.y = cam_x + WIDTH + margin, random.uniform(0, HEIGHT)
        elif side == "T":
            self.x, self.y = cam_x + random.uniform(0, WIDTH + 300), -margin
        else:
            self.x, self.y = cam_x + random.uniform(0, WIDTH + 300), HEIGHT + margin
        tx = cam_x + random.uniform(WIDTH * 0.2, WIDTH * 0.8)
        ty = random.uniform(HEIGHT * 0.2, HEIGHT * 0.8)
        speed = random.uniform(*self.speed_range)
        d = math.hypot(tx - self.x, ty - self.y) or 1.0
        self.vx, self.vy = (tx - self.x) / d * speed, (ty - self.y) / d * speed
        self.angle = random.uniform(0, math.tau)
        self.spin = random.uniform(-1.5, 1.5)
        # Jagged outline: (angle, radius factor) pairs.
        self.shape = [(i * math.tau / 9, random.uniform(0.7, 1.15)) for i in range(9)]

    def move(self, dt, cam_x):
        """Advance one step. Returns True once it has left the view for good."""
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.angle += self.spin * dt
        m = 60
        return ((self.x < cam_x - m and self.vx <= 0) or self.x < cam_x - 300 or
                (self.x > cam_x + WIDTH + m and self.vx >= 0) or
                (self.y < -m and self.vy <= 0) or (self.y > HEIGHT + m and self.vy >= 0))

    def points(self, cam_x):
        pts = []
        for a, f in self.shape:
            pts.extend([self.x - cam_x + math.cos(a + self.angle) * self.radius * f,
                        self.y + math.sin(a + self.angle) * self.radius * f])
        return pts


class Asteroid(Drifter):
    """A deadly rock. Respawns from a screen edge when it has passed."""

    def update(self, dt, cam_x):
        if self.move(dt, cam_x):
            self.spawn(cam_x)


class FuelPickup(Drifter):
    """A rare fuel cell. Touching it refills the tank completely."""
    radius_range = (14, 14)
    speed_range = (25, 45)
    sides = "R"            # always drifts in from the right, towards you


def blend(c1, c2, t):
    """Linear blend between two '#rrggbb' colors."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


class GravityArena:
    def __init__(self, root):
        self.root = root
        root.title("Gravity Arena — Gravity Assist")
        root.geometry(f"{WIDTH}x{HEIGHT + 85}")
        root.resizable(False, False)

        self.state = "ready"      # ready / playing / crashed / escaped
        self.fuel = 0.0

        controls = ttk.Frame(root, padding=8)
        controls.pack(fill="x")

        ttk.Label(controls, text="Gravity:").pack(side="left")
        self.gravity = tk.DoubleVar(value=1.0)
        ttk.Scale(controls, from_=0.3, to=2.5, variable=self.gravity, orient="horizontal",
                  length=140, takefocus=False).pack(side="left", padx=(4, 16))

        ttk.Label(controls, text="Fuel:").pack(side="left")
        self.fuel_level = tk.DoubleVar(value=5)
        self.fuel_label = ttk.Label(controls, text="5", width=2)
        ttk.Scale(controls, from_=1, to=FUEL_MAX_LEVEL, variable=self.fuel_level, orient="horizontal",
                  length=140, takefocus=False, command=self.on_fuel_change).pack(side="left", padx=(4, 2))
        self.fuel_label.pack(side="left", padx=(0, 16))

        ttk.Button(controls, text="Start / Pause", command=self.toggle_pause,
                   takefocus=False).pack(side="left", padx=(0, 8))

        self.show_vectors = True
        self.vec_text = tk.StringVar(value="Vectors: ON")
        ttk.Button(controls, textvariable=self.vec_text, command=self.toggle_vectors,
                   takefocus=False, width=12).pack(side="left")

        self.canvas = tk.Canvas(root, width=WIDTH, height=HEIGHT, bg="#07111f", highlightthickness=0)
        self.canvas.pack()
        self.status = ttk.Label(root, text="")
        self.status.pack(fill="x", padx=8, pady=6)

        self.paused = False
        self.end_info = ""
        self.elapsed = 0.0
        self.hover = None
        self.ship = {}
        self.bodies = []
        self.asteroids = []
        self.pickups = []         # fuel cells (up to two at a time)
        self.pickup_timer = 20.0  # seconds of play until the next fuel cell may appear
        self.refuel_flash = 0.0
        self.anim = 0             # animation counter (for pulsing glow)
        self.accel = (0.0, 0.0)   # total acceleration (gravity + thrust), for the vector
        self.trail = []           # recent ship positions (world coordinates)
        self.flame = False
        self.braking = False
        self.end_speed = 0        # speed (m/s) when the run ended
        self.out_time = 0.0       # seconds spent outside the playfield
        self.frame = 0
        self.cam_x = 0.0          # world x at the left edge of the screen
        self.gen_x = 0.0          # world x up to which planets have been generated
        self.seed = 0
        self.world_rng = random.Random(0)
        self.distance = 0.0       # furthest x reached (pixels)
        self.best = 0             # best distance this session (meters)
        self.new_best = False

        # Background stars: [x, y, size, drift speed (px/s), color]. Bigger = closer = faster.
        self.stars = []
        for _ in range(130):
            size = random.choice([1, 1, 2])
            speed = 5.0 if size == 1 else 12.0
            self.stars.append([random.uniform(0, WIDTH), random.uniform(0, HEIGHT), size,
                               speed * random.uniform(0.8, 1.2), random.choice(STAR_COLORS)])

        self.keys = set()
        root.bind("<KeyPress>", self.key_down)
        root.bind("<KeyRelease>", self.key_up)
        self.canvas.bind("<Button-1>", self.mouse_click)
        self.canvas.bind("<Motion>", self.mouse_move)
        self.new_system()
        self.tick()

    # ------------------------------------------------------------------ fuel
    def fuel_capacity(self):
        level = round(self.fuel_level.get())
        return math.inf if level >= FUEL_MAX_LEVEL else level * FUEL_SECONDS_PER_LEVEL

    def on_fuel_change(self, *_):
        level = round(self.fuel_level.get())
        self.fuel_label.config(text="∞" if level >= FUEL_MAX_LEVEL else str(level))
        if self.state == "ready":     # only takes effect before launch
            self.fuel = self.fuel_capacity()

    # ------------------------------------------------------------------ world
    def distance_m(self):
        return int(self.distance / PX_PER_METER)

    def new_system(self):
        """Brand new random world."""
        self.seed = random.randrange(10 ** 9)
        self.reset_ship()

    def generate_world(self):
        """Keep generating planets ahead of the camera, forever."""
        rng = self.world_rng
        while self.gen_x < self.cam_x + WIDTH + 700:
            # Always >= 170 px apart in x, so planets never overlap each other.
            x = self.gen_x + rng.uniform(170, 330)
            y = rng.randint(70, HEIGHT - 70)
            radius = rng.randint(12, 32)
            recent = {b.name for b in self.bodies[-5:]}          # avoid repeating a nearby name
            name = rng.choice([n for n in EXOPLANETS if n not in recent])
            self.bodies.append(Body(x, y, radius, rng.choice(COLORS), name))
            self.gen_x = x

    def reset_ship(self):
        """(Re)start the current world. Ship starts completely still and waits for the first thrust."""
        self.world_rng = random.Random(self.seed)
        self.bodies = []
        self.gen_x = 150.0
        self.cam_x = 0.0
        self.generate_world()
        self.ship = {"x": SHIP_START[0], "y": SHIP_START[1], "vx": 0.0, "vy": 0.0, "angle": 0.0}
        self.asteroids = [Asteroid(0.0) for _ in range(4)]
        self.pickups = []
        self.pickup_timer = random.uniform(3, 6)
        self.refuel_flash = 0.0
        self.fuel = self.fuel_capacity()
        self.accel = (0.0, 0.0)
        self.trail = []
        self.flame = False
        self.distance = 0.0
        self.new_best = False
        self.out_time = 0.0
        self.elapsed = 0.0
        self.paused = False
        self.set_state("ready")

    def set_state(self, state, info=""):
        self.state = state
        self.end_info = info
        if state in END_STATES:
            d = self.distance_m()
            self.end_speed = int(math.hypot(self.ship['vx'], self.ship['vy']) / PX_PER_METER)
            self.new_best = d > self.best
            self.best = max(self.best, d)
            self.status.config(text="Press R for a new world, T to retry, Q to quit, or use the buttons.")
        else:
            self.status.config(text="W/↑ thrust • S/↓ brake (both use fuel) • A/D rotate • Space start/pause • R new world • T retry")

    def toggle_vectors(self):
        self.show_vectors = not self.show_vectors
        self.vec_text.set("Vectors: ON" if self.show_vectors else "Vectors: OFF")
        self.canvas.focus_set()

    def toggle_pause(self):
        if self.state == "ready":
            self.set_state("playing")
        elif self.state == "playing":
            self.paused = not self.paused
        self.canvas.focus_set()

    # ------------------------------------------------------------------ input
    def key_down(self, event):
        k = event.keysym.lower()
        if k == "space" and "space" not in self.keys:
            self.toggle_pause()
        self.keys.add(k)
        if k == "r":
            self.new_system()
        elif k == "t":
            self.reset_ship()
        elif k == "q" and self.state in END_STATES:
            self.root.destroy()

    def key_up(self, event):
        self.keys.discard(event.keysym.lower())

    def mouse_click(self, event):
        if self.state in END_STATES:
            for x1, y1, x2, y2, _label, cb in self.menu_buttons():
                if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                    cb()
                    return

    def mouse_move(self, event):
        self.hover = None
        if self.state in END_STATES:
            for i, (x1, y1, x2, y2, _l, _cb) in enumerate(self.menu_buttons()):
                if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                    self.hover = i

    # ------------------------------------------------------------------ simulation
    def update_background(self):
        for s in self.stars:
            s[0] -= s[3] * DT
            s[1] += s[3] * 0.15 * DT
            if s[0] < -3:
                s[0] = WIDTH + 2
                s[1] = random.uniform(0, HEIGHT)
            if s[1] > HEIGHT + 3:
                s[1] = -2

    def update(self):
        self.update_background()
        self.flame = False
        self.braking = False
        if self.paused or self.state in END_STATES:
            return
        dt = DT

        # Steering (rotation is free)
        if "a" in self.keys or "left" in self.keys:
            self.ship["angle"] -= 2.8 * dt
        if "d" in self.keys or "right" in self.keys:
            self.ship["angle"] += 2.8 * dt

        thrusting = "w" in self.keys or "up" in self.keys
        if self.state == "ready":
            # Ship floats motionless until the player launches it.
            if thrusting:
                self.set_state("playing")
            else:
                return

        # Thrust burns fuel
        thr_ax = thr_ay = 0.0
        if thrusting and self.fuel > 0:
            thr_ax = math.cos(self.ship["angle"]) * SHIP_THRUST
            thr_ay = math.sin(self.ship["angle"]) * SHIP_THRUST
            self.ship["vx"] += thr_ax * dt
            self.ship["vy"] += thr_ay * dt
            self.flame = True
            if self.fuel != math.inf:
                self.fuel = max(0.0, self.fuel - dt)
        elif ("s" in self.keys or "down" in self.keys) and self.fuel > 0:
            # Brake: push against the direction of travel, weaker than thrust and cheaper on fuel
            vx, vy = self.ship["vx"], self.ship["vy"]
            speed = math.hypot(vx, vy)
            if speed > 1.0:
                a_b = min(BRAKE_DECEL, speed / dt)       # never reverse the ship
                thr_ax, thr_ay = -vx / speed * a_b, -vy / speed * a_b
                self.ship["vx"] += thr_ax * dt
                self.ship["vy"] += thr_ay * dt
                self.braking = True
                if self.fuel != math.inf:
                    self.fuel = max(0.0, self.fuel - dt * BRAKE_FUEL_RATE)

        self.elapsed += dt
        x, y = self.ship["x"], self.ship["y"]

        # Gravity from each planet. Softening prevents enormous acceleration at close range.
        ax = ay = 0.0
        g = G * self.gravity.get()
        for body in self.bodies:
            dx, dy = body.x - x, body.y - y
            r2 = dx * dx + dy * dy
            if r2 < (body.radius + 10) ** 2:
                self.set_state("crashed", f"You crashed into {body.name}.")
                return
            softened = max(r2, 45 ** 2)
            accel = g * body.mass / (softened ** 1.5)   # = G*m/r^2 divided by r, times dx
            ax += dx * accel
            ay += dy * accel

        self.ship["vx"] += ax * dt
        self.ship["vy"] += ay * dt
        self.accel = (ax + thr_ax, ay + thr_ay)
        self.frame += 1
        if self.frame % TRAIL_EVERY == 0:
            self.trail.append((self.ship["x"], self.ship["y"]))
            del self.trail[:-TRAIL_MAX]
        self.ship["x"] += self.ship["vx"] * dt
        self.ship["y"] += self.ship["vy"] * dt

        # Camera only scrolls forward (to the right)
        target_cam = self.ship["x"] - WIDTH * CAMERA_LEAD
        if target_cam > self.cam_x:
            self.cam_x += (target_cam - self.cam_x) * min(1.0, 5 * dt)
        self.distance = max(self.distance, self.ship["x"] - SHIP_START[0])

        # Endless world: generate ahead, forget what's far behind
        self.generate_world()
        self.bodies = [b for b in self.bodies if b.x > self.cam_x - 300]

        # More asteroids the further you get
        wanted = min(9, 4 + self.distance_m() // 300)
        while len(self.asteroids) < wanted:
            self.asteroids.append(Asteroid(self.cam_x))

        # Rare fuel cells drift by; grabbing one refills the tank completely.
        self.refuel_flash = max(0.0, self.refuel_flash - dt)
        if self.fuel_capacity() != math.inf:
            if len(self.pickups) < 2:
                self.pickup_timer -= dt
                if self.pickup_timer <= 0:
                    self.pickups.append(FuelPickup(self.cam_x))
                    self.pickup_timer = random.uniform(6, 12)
            for p in self.pickups[:]:
                gone = p.move(dt, self.cam_x)
                if math.hypot(p.x - self.ship["x"], p.y - self.ship["y"]) < p.radius + SHIP_RADIUS + 6:
                    self.fuel = self.fuel_capacity()
                    self.refuel_flash = 1.5
                    gone = True
                if gone:
                    self.pickups.remove(p)

        # Asteroids drift through the screen; touching one is fatal.
        for a in self.asteroids:
            a.update(dt, self.cam_x)
            if math.hypot(a.x - self.ship["x"], a.y - self.ship["y"]) < a.radius + SHIP_RADIUS:
                self.set_state("crashed", "You hit an asteroid.")
                return

        # Leaving the top, bottom or back of the screen is allowed for a few seconds.
        if self.ship["x"] < self.cam_x or not (0 <= self.ship["y"] <= HEIGHT):
            self.out_time += dt
            if self.out_time >= OUT_GRACE:
                self.set_state("escaped", "You stayed out of bounds too long.")
        else:
            self.out_time = 0.0

    # ------------------------------------------------------------------ drawing
    def rounded_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2,
               x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
        return self.canvas.create_polygon(pts, smooth=True, **kw)

    def menu_buttons(self):
        cx, cy = WIDTH // 2, HEIGHT // 2
        top = cy + 72
        return [
            (cx - 185, top, cx - 10, top + 46, "Try again", self.reset_ship),
            (cx + 10, top, cx + 185, top + 46, "New world", self.new_system),
        ]

    def draw_game_over(self):
        c = self.canvas
        cx, cy = WIDTH // 2, HEIGHT // 2
        theme = {
            "crashed": ("CRASHED!", "#ff5d73"),
            "escaped": ("LOST IN SPACE", "#ffb703"),
        }
        title, accent = theme[self.state]

        # Dim the scene (stipple isn't supported on macOS Tk, so skip it there)
        if sys.platform != "darwin":
            c.create_rectangle(0, 0, WIDTH, HEIGHT, fill="#000000", stipple="gray50", outline="")

        # Panel with a soft glow
        for i, col in enumerate(["#0d1b2e", "#12263d", "#183250"]):
            pad = 10 - i * 3
            self.rounded_rect(cx - 230 - pad, cy - 135 - pad, cx + 230 + pad, cy + 150 + pad, 28, fill=col, outline="")
        self.rounded_rect(cx - 230, cy - 135, cx + 230, cy + 150, 24, fill="#0b1626", outline=accent, width=2)
        c.create_line(cx - 80, cy - 72, cx + 80, cy - 72, fill=accent, width=2)

        c.create_text(cx, cy - 102, text=title, fill=accent, font=("Arial", 28, "bold"))
        c.create_text(cx, cy - 48, text=self.end_info, fill="#dce7f5", font=("Arial", 13))

        dist_text = f"Distance: {self.distance_m()} m" + ("  •  NEW BEST!" if self.new_best else "")
        c.create_text(cx, cy - 16, text=dist_text, fill="#ffd166" if self.new_best else "#ffffff",
                      font=("Arial", 18, "bold"))
        c.create_text(cx, cy + 14, text=f"Speed: {self.end_speed} m/s", fill="#dce7f5", font=("Arial", 13, "bold"))
        c.create_text(cx, cy + 40, text=f"Best: {self.best} m   •   Time: {self.elapsed:.1f} s",
                      fill="#8fa8c2", font=("Arial", 11))

        for i, (x1, y1, x2, y2, label, _cb) in enumerate(self.menu_buttons()):
            hot = self.hover == i
            fill = accent if hot else "#13243a"
            txt = "#07111f" if hot else accent
            self.rounded_rect(x1, y1, x2, y2, 14, fill=fill, outline=accent, width=2)
            c.create_text((x1 + x2) / 2, (y1 + y2) / 2, text=label, fill=txt, font=("Arial", 12, "bold"))

        c.create_text(cx, cy + 136, text="R = new world   •   T = retry   •   Q = quit", fill="#5d7592", font=("Arial", 9))

    def draw_edges(self, sx, sy):
        """Soft glow on the stretch of edge nearest the rocket: yellow when close, blinking red when beyond."""
        c = self.canvas
        blink = (self.anim // 8) % 2 == 0
        bg, layers, thick = "#07111f", 5, 4

        def glow(edge, center, base, strength):
            limit = HEIGHT if edge == "left" else WIDTH
            n = EDGE_SPAN // EDGE_SEG
            for k in range(-n, n):
                p0 = center + k * EDGE_SEG
                p1 = p0 + EDGE_SEG
                if p1 <= 0 or p0 >= limit:
                    continue
                p0, p1 = max(p0, 0), min(p1, limit)
                u = abs(k + 0.5) * EDGE_SEG / EDGE_SPAN          # 0 at the rocket, 1 at the glow's end
                fade = (1 - u) ** 2
                for i in range(layers):
                    col = blend(bg, base, strength * fade * (1 - i / layers) ** 1.5)
                    a, b = i * thick, (i + 1) * thick
                    if edge == "top":
                        c.create_rectangle(p0, a, p1, b, fill=col, outline="")
                    elif edge == "bottom":
                        c.create_rectangle(p0, HEIGHT - b, p1, HEIGHT - a, fill=col, outline="")
                    else:
                        c.create_rectangle(a, p0, b, p1, fill=col, outline="")

        for edge, d, along, in (("top", sy, sx), ("bottom", HEIGHT - sy, sx), ("left", sx, sy)):
            if d >= EDGE_ZONE:
                continue
            center = int(min(max(along, 0), HEIGHT if edge == "left" else WIDTH))
            if d < 0:
                if blink:
                    glow(edge, center, "#ff3b4a", 0.75)
            else:
                glow(edge, center, "#ffd54a", 0.5 * (1 - d / EDGE_ZONE))

        # The rocket is off-screen: show a marker at the edge where it is
        if sx < 0 or sy < 0 or sy > HEIGHT:
            mx, my = min(max(sx, 14), WIDTH - 14), min(max(sy, 14), HEIGHT - 14)
            n = math.hypot(sx - mx, sy - my) or 1.0
            ux, uy = (sx - mx) / n, (sy - my) / n
            qx, qy = -uy, ux
            c.create_polygon(mx + ux * 8, my + uy * 8,
                             mx - ux * 5 + qx * 6, my - uy * 5 + qy * 6,
                             mx - ux * 5 - qx * 6, my - uy * 5 - qy * 6,
                             fill="#ff4d5e", outline="")

    def draw_fuel_gauge(self):
        c = self.canvas
        x0, y0, w, h = 12, 12, 150, 10
        c.create_text(x0, y0 - 2, anchor="nw", text="FUEL", fill="#8fa8c2", font=("Arial", 9, "bold"))
        bx = x0 + 40
        c.create_rectangle(bx, y0, bx + w, y0 + h, outline="#2a4a66")
        if self.fuel == math.inf:
            c.create_rectangle(bx, y0, bx + w, y0 + h, fill="#67e8f9", outline="")
            c.create_text(bx + w + 8, y0 - 4, anchor="nw", text="∞", fill="#67e8f9", font=("Arial", 12, "bold"))
            return
        frac = max(0.0, min(1.0, self.fuel / self.fuel_capacity()))
        col = "#80ed99" if frac > 0.5 else "#ffd166" if frac > 0.2 else "#ff5d73"
        if frac > 0:
            c.create_rectangle(bx, y0, bx + w * frac, y0 + h, fill=col, outline="")
        else:
            c.create_text(bx + w + 8, y0 - 2, anchor="nw", text="EMPTY", fill="#ff5d73", font=("Arial", 9, "bold"))
        if self.refuel_flash > 0:
            c.create_text(bx + w + 8, y0 - 2, anchor="nw", text="REFUELED!", fill="#80ed99", font=("Arial", 9, "bold"))

    def draw_hud(self):
        c = self.canvas
        c.create_text(WIDTH - 14, 10, anchor="ne", text=f"{self.distance_m()} m",
                      fill="#dce7f5", font=("Arial", 20, "bold"))
        c.create_text(WIDTH - 14, 40, anchor="ne", text=f"BEST {self.best} m",
                      fill="#8fa8c2", font=("Arial", 9, "bold"))

    def draw(self):
        c = self.canvas
        cam = self.cam_x
        c.delete("all")

        # Stars with a little parallax from the camera
        for sx, sy, size, _spd, col in self.stars:
            px = (sx - cam * (0.12 if size == 1 else 0.25)) % WIDTH
            c.create_oval(px, sy, px + size, sy + size, fill=col, outline="")

        # Edge warning glow: drawn early so it sits behind the rocket and everything else
        x, y = self.ship["x"] - cam, self.ship["y"]
        if self.state in ("ready", "playing"):
            self.draw_edges(x, y)

        # Planets with gravity field hints (field rings scale with planet size)
        for body in self.bodies:
            bx = body.x - cam
            r1, r2 = body.radius * 3.25, body.radius * 1.75
            if bx < -r1 or bx > WIDTH + r1:
                continue
            c.create_oval(bx-r1, body.y-r1, bx+r1, body.y+r1, outline="#1c3b54")
            c.create_oval(bx-r2, body.y-r2, bx+r2, body.y+r2, outline="#214a66")
            c.create_oval(bx-body.radius, body.y-body.radius, bx+body.radius, body.y+body.radius,
                          fill=body.color, outline="white", width=1)
            c.create_text(bx, body.y+body.radius+13, text=body.name, fill="#b7c9dc", font=("Arial", 8))

        # Asteroids
        for a in self.asteroids:
            if -40 < a.x - cam < WIDTH + 40:
                c.create_polygon(a.points(cam), fill="#6c7a89", outline="#c5cdd6", width=1)

        # Fuel cells
        for p in self.pickups:
            px, py = p.x - cam, p.y
            if -40 < px < WIDTH + 40:
                glow = p.radius + 5 + 2 * math.sin(self.anim * 0.1)
                c.create_oval(px-glow, py-glow, px+glow, py+glow, outline="#1f6f4a")
                c.create_oval(px-p.radius, py-p.radius, px+p.radius, py+p.radius,
                              fill="#0d2b22", outline="#80ed99", width=2)
                k = p.radius / 11
                bolt = [(1, -7), (-4, 1), (0, 1), (-1, 7), (4, -1), (0, -1)]
                c.create_polygon([v for bx_, by_ in bolt for v in (px + bx_ * k, py + by_ * k)],
                                 fill="#80ed99", outline="")

        # Short path trail that fades quickly
        n = len(self.trail)
        for i, (px, py) in enumerate(self.trail):
            t = 1 - (n - 1 - i) / TRAIL_MAX          # 1 = newest
            col = blend("#0a1c30", "#67e8f9", t ** 1.5)
            r = 0.8 + 1.2 * t
            c.create_oval(px-cam-r, py-r, px-cam+r, py+r, fill=col, outline="")

        # Rocket (local coords: nose points along +x)
        ang = self.ship["angle"]
        ca, sa = math.cos(ang), math.sin(ang)

        def rot(pts):
            out = []
            for px, py in pts:
                out.extend([x + px * ca - py * sa, y + px * sa + py * ca])
            return out

        if self.flame:
            fl = random.uniform(9, 17)
            c.create_polygon(rot([(-9, -3), (-9 - fl, 0), (-9, 3)]), fill="#ffb703", outline="")
            c.create_polygon(rot([(-9, -1.5), (-9 - fl * 0.55, 0), (-9, 1.5)]), fill="#fff3b0", outline="")
        if self.braking:
            bl = random.uniform(5, 9)
            c.create_polygon(rot([(13, -2.5), (13 + bl, 0), (13, 2.5)]), fill="#67e8f9", outline="")
        c.create_polygon(rot([(-9, -4), (-15, -9), (-3, -4)]), fill="#67e8f9", outline="")   # fins
        c.create_polygon(rot([(-9, 4), (-15, 9), (-3, 4)]), fill="#67e8f9", outline="")
        c.create_polygon(rot([(-9, -4), (6, -4), (6, 4), (-9, 4)]), fill="#f8f9fa", outline="#9fb4c7")  # body
        c.create_polygon(rot([(6, -4), (16, 0), (6, 4)]), fill="#ff5d73", outline="")                  # nose
        c.create_oval(x-2.5, y-2.5, x+2.5, y+2.5, fill="#4cc9f0", outline="")                          # window

        if self.show_vectors:
            # Velocity vector (yellow)
            c.create_line(x, y, x+self.ship["vx"]*0.25, y+self.ship["vy"]*0.25, fill="#ffb703", width=2, arrow="last")
            # Acceleration vector (red): gravity + thrust
            ax, ay = self.accel
            if math.hypot(ax, ay) > 2:
                c.create_line(x, y, x+ax*0.35, y+ay*0.35, fill="#ff5d73", width=2, arrow="last")

        self.draw_fuel_gauge()
        self.draw_hud()

        if self.paused and self.state == "playing":
            c.create_text(WIDTH // 2, HEIGHT // 2 - 10, text="PAUSED", fill="#67e8f9", font=("Arial", 30, "bold"))
            c.create_text(WIDTH // 2, HEIGHT // 2 + 28, text="Press Space to resume", fill="#8fa8c2", font=("Arial", 11))

        if self.state in END_STATES:
            self.draw_game_over()

    def tick(self):
        self.anim += 1
        self.update()
        self.draw()
        self.root.after(16, self.tick)


def main():
    root = tk.Tk()
    GravityArena(root)
    root.mainloop()


if __name__ == "__main__":
    main()