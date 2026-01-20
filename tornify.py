import flet as ft
import flet.canvas as cv
import random
import math
import asyncio
import sys, os
from collections import defaultdict

def resource_path(relative_path):
    """Ajusta o caminho de arquivos quando o app é empacotado em .exe"""
    try:
        base_path = sys._MEIPASS  # Pasta temporária usada pelo PyInstaller
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class Player:
    def __init__(self, id, name):
        self.id = id
        self.name = name
        self.score = 0
        self.losses = 0

class Match:
    def __init__(self, player1=None, player2=None, previous1=None, previous2=None, use_losers=False, is_champion_slot=False, set_parent=True):
        self.player1 = player1
        self.player2 = player2
        self.previous1 = previous1
        self.previous2 = previous2
        # only set the parent on the previous matches when requested.
        # This avoids overwriting existing parent links (important for third-place match).
        if set_parent:
            if self.previous1:
                self.previous1.parent = self
            if self.previous2:
                self.previous2.parent = self
        self.winner = None
        self.parent = None
        self.update_func = None
        self.id = None
        self._had_winner = False
        self.p1_series = 0
        self.p2_series = 0
        self.best_of = 1
        # flags for special behavior
        self.use_losers = use_losers
        self.is_champion_slot = is_champion_slot
        if self.player1 is None and self.player2 is not None:
            self.winner = self.player2
        elif self.player2 is None and self.player1 is not None:
            self.winner = self.player1

    def get_player1(self):
        # If this match is configured to use losers, fetch the loser from previous1
        if self.use_losers:
            if self.previous1:
                return self.previous1.get_loser()
            return None
        if self.player1 is not None:
            return self.player1
        if self.previous1 and self.previous1.winner:
            return self.previous1.winner
        return None

    def get_player2(self):
        if self.use_losers:
            if self.previous2:
                return self.previous2.get_loser()
            return None
        if self.player2 is not None:
            return self.player2
        if self.previous2 and self.previous2.winner:
            return self.previous2.winner
        return None

    def get_loser(self):
        # Return the loser of this match (only valid if winner is set)
        p1 = self.get_player1()
        p2 = self.get_player2()
        if self.winner is None:
            return None
        if p1 and p2:
            return p2 if self.winner == p1 else p1
        return None

def main(page: ft.Page):
    page.title = "Tornify"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.window.icon = "assets/trophy.png"
    page.update()

    players = []  # Lista para armazenar os jogadores
    player_id_counter = [0]
    edit_mode = False  # Modo de edição desligado inicialmente
    tournament_running = False
    all_matches = []
    theme_vars = {}
    bottom_part = None  # Will be defined later
    connector_canvases = []
    dragging = [None]
    bracket_row = None
    
    # Referências para controle de layout e zoom
    tournament_bracket_container = None
    base_bracket_width = 0
    base_bracket_height = 0
    
    connector_width = 40
    base_spacing = 20

    # Third-place rectangle reference so we can update theme live
    third_place_rectangle = [None]  # container reference

    # Zoom related variables (affect only the tournament bracket container)
    zoom_factor = {"value": 1.0}  # wrapped in dict to allow closures to modify
    min_zoom = 0.5
    max_zoom = 2.5
    zoom_step = 0.1

    # Keep rounds_list for re-rendering at different zoom levels
    rounds_list_global = {"value": None}
    third_place_match_global = {"value": None}
    champion_match_global = {"value": None}

    # Create confetti canvas at the beginning
    confetti_canvas = cv.Canvas(shapes=[], expand=True)
    overlay = ft.TransparentPointer(content=confetti_canvas, visible=False)
    confettis = []
    animating = False

    async def animate_confetti():
        nonlocal animating, confettis
        animating = True
        while confettis:
            for c in confettis[:]:
                c.y += c.dy
                c.x += c.dx
                c.dy += 0.2
                c.dx += random.uniform(-0.5, 0.5)
                c.dx = max(-3, min(3, c.dx))
                if c.y > page.height:
                    confettis.remove(c)
            confetti_canvas.shapes = []
            for c in confettis:
                paint = ft.Paint(color=c.color, style=ft.PaintingStyle.FILL)
                rect = cv.Rect(
                    x=c.x,
                    y=c.y,
                    width=c.width,
                    height=c.height,
                    paint=paint
                )
                confetti_canvas.shapes.append(rect)
            confetti_canvas.update()
            await asyncio.sleep(0.03)
        overlay.visible = False
        page.update()
        animating = False

    class ConfettiPiece:
        def __init__(self, width, height):
            self.x = random.uniform(0, width)
            self.y = random.uniform(-50, 0)
            self.width = random.uniform(4, 10)
            self.height = random.uniform(6, 12)
            self.color = random.choice(["#f44336", "#e91e63", "#9c27b0", "#673ab7", "#3f51b5",
                "#2196f3", "#03a9f4", "#00bcd4", "#009688", "#4caf50",
                "#8bc34a", "#cddc39", "#ffeb3b", "#ffc107", "#ff9800"])
            self.dx = random.uniform(-3, 3)
            self.dy = random.uniform(2, 6)

    async def trigger_confetti():
        nonlocal confettis, animating
        confettis.extend([ConfettiPiece(page.width, page.height) for _ in range(100)])
        if not overlay.visible:
            overlay.visible = True
            page.update()
        if not animating:
            page.run_task(animate_confetti)

    def apply_transform():
        try:
            current_zoom = zoom_factor["value"]
            if tournament_bracket_container is not None and rounds_list_global["value"] is not None:
                tournament_bracket_container.width = int(base_bracket_width * current_zoom)
                tournament_bracket_container.height = int(base_bracket_height * current_zoom)
                render_bracket(current_zoom)
        except Exception as e:
            print(f"Zoom error: {e}")
        page.update()

    def zoom_in(e=None):
        zoom_factor["value"] = min(max_zoom, round(zoom_factor["value"] + zoom_step, 2))
        apply_transform()

    def zoom_out(e=None):
        zoom_factor["value"] = max(min_zoom, round(zoom_factor["value"] - zoom_step, 2))
        apply_transform()

    def on_keyboard(e: ft.KeyboardEvent):
        if e.key == 'F11' or (e.key == 'Enter' and e.alt):
            page.window.full_screen = not page.window.full_screen
            page.update()
            return

        if e.control and (e.key in ('ArrowUp', 'Plus', '+', 'Equal', '=')):
            zoom_in()
            return

        if e.control and (e.key in ('ArrowDown', 'Minus', '-')):
            zoom_out()
            return

    page.on_keyboard_event = on_keyboard

    def on_wheel(e):
        try:
            ctrl_pressed = getattr(e, "control", False) or getattr(e, "ctrlKey", False)
            delta = 0
            if hasattr(e, "delta"):
                d = e.delta
                if isinstance(d, (list, tuple)):
                    delta = d[1] if len(d) > 1 else d[0]
                elif isinstance(d, dict):
                    delta = d.get("y", 0)
                else:
                    try:
                        delta = float(d)
                    except Exception:
                        delta = 0
            else:
                delta = getattr(e, "deltaY", 0)
        except Exception:
            ctrl_pressed = False
            delta = 0

        if ctrl_pressed:
            if delta < 0:
                zoom_in()
            elif delta > 0:
                zoom_out()

    try:
        setattr(page, "on_wheel", on_wheel)
    except Exception:
        try:
            setattr(page, "on_pointer_wheel", on_wheel)
        except Exception:
            pass

    def get_elim_round_label(matches_count: int, level_index: int, num_rounds: int) -> str:
        if level_index == num_rounds - 1:
            return "Campeão"
        if level_index == num_rounds - 2:
            return "Final"

        players_remaining = matches_count * 2

        mapping = {
            4: "Semifinal",
            8: "Quartas de Final",
            16: "Oitavas de Final"
        }
        if players_remaining == 2:
            return "Final"
        if players_remaining in mapping:
            return mapping[players_remaining]
        if players_remaining > 16 and players_remaining % 2 == 0:
            denom = players_remaining // 2
            return f"1/{denom} de Final"
        return f"Round of {players_remaining}"

    def toggle_edit(e):
        nonlocal edit_mode
        edit_mode = not edit_mode
        apply_theme(None)
        page.update()

    third_place_checkbox = ft.Checkbox(label="Incluir 3º Lugar", value=True)

    buttons = [
        ft.ElevatedButton("▶️ Iniciar", on_click=lambda e: start_tournament(e)),
        ft.ElevatedButton("🎲 Randomizar", on_click=lambda e: randomize(e)),
        ft.ElevatedButton("✏️ Editar", on_click=toggle_edit),
        ft.ElevatedButton("🔄 Resetar", on_click=lambda e: reset(e)),
        ft.ElevatedButton("⬅️ Voltar para Edição", on_click=lambda e: back_to_edit(e)),
        ft.ElevatedButton("Tutorial", on_click=lambda e: show_tutorial(e)),
        ft.ElevatedButton("🔍+", on_click=lambda e: zoom_in(e)),
        ft.ElevatedButton("🔍-", on_click=lambda e: zoom_out(e)),
    ]
    edit_button = buttons[2]

    def find_index_of_control(row_control: ft.Row):
        try:
            controls_list = bottom_part.content.controls if isinstance(bottom_part.content, ft.Column) else bottom_part.content.content.controls
            return controls_list.index(row_control)
        except ValueError:
            return -1
        except AttributeError:
            return -1

    def edit_name(e):
        if not edit_mode or tournament_running:
            return
        
        detector = e.control
        row = detector.parent
        if isinstance(bottom_part.content, ft.Column):
            controls_list = bottom_part.content.controls
        else:
            return

        try:
            index = controls_list.index(row)
        except ValueError:
            return

        container = detector.content
        old_name = players[index].name

        edit_field = ft.TextField(
            value=old_name,
            width=200,
            height=40,
            border_radius=20,
            content_padding=10,
            text_align=ft.TextAlign.CENTER,
            border_width=0,
            on_submit=lambda e_submit: confirm_edit(e_submit, index, container, detector),
            on_blur=lambda e_blur: cancel_edit(index, container, detector)
        )
        container.content = edit_field
        apply_theme(None)
        edit_field.focus()
        page.update()

    def confirm_edit(e, index, container: ft.Container, detector: ft.GestureDetector):
        new_name = e.control.value.strip()
        
        if new_name:
            players[index].name = new_name
            container.content = ft.Text(new_name, size=16)
        else:
            container.content = ft.Text(players[index].name, size=16)
            
        apply_theme(None)
        page.update()

    def cancel_edit(index, container: ft.Container, detector: ft.GestureDetector):
        if isinstance(container.content, ft.TextField):
            container.content = ft.Text(players[index].name, size=16)
            apply_theme(None)
            page.update()

    def direct_delete(e): 
        if tournament_running:
            return
        detector = e.control
        row = detector.parent
        
        if isinstance(bottom_part.content, ft.Column):
            controls_list = bottom_part.content.controls
        else:
            return

        try:
            index = controls_list.index(row)
        except ValueError:
            return
        
        if index == -1 or not edit_mode:
            return

        del players[index]
        controls_list.pop(index)
        page.update()

    def reset(e):
        players.clear()
        back_to_edit(e)

    def randomize(e):
        if not tournament_running:
            random.shuffle(players)
            rebuild_list()
            apply_theme(None)
        else:
            leaf_matches = [m for m in all_matches if m.previous1 is None and m.previous2 is None]
            leaf_players = [p for m in leaf_matches for p in (m.player1, m.player2) if p is not None]
            random.shuffle(leaf_players)
            idx = 0
            for m in leaf_matches:
                if m.player1 is not None:
                    m.player1 = leaf_players[idx]
                    idx += 1
                if m.player2 is not None:
                    m.player2 = leaf_players[idx]
                    idx += 1
                if m.player1 is None or m.player2 is None:
                    m.winner = m.player1 or m.player2
                else:
                    m.winner = None
                    m.p1_series = 0
                    m.p2_series = 0
            for m in all_matches:
                if m.previous1 or m.previous2:
                    m.winner = None
                    m.p1_series = 0
                    m.p2_series = 0
                if hasattr(m, '_had_winner'):
                    m._had_winner = False
            update_all()
        page.update()

    def back_to_edit(e):
        nonlocal tournament_running, bracket_row, tournament_bracket_container
        tournament_running = False
        connector_canvases.clear()
        all_matches.clear()
        bracket_row = None
        tournament_bracket_container = None
        third_place_rectangle[0] = None
        rounds_list_global["value"] = None
        third_place_match_global["value"] = None
        champion_match_global["value"] = None
        
        bottom_part.content = ft.Column(
            [],
            expand=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.START,
            scroll=ft.ScrollMode.AUTO
        )
        
        rebuild_list()
        apply_theme(None)

    def rebuild_list():
        if not isinstance(bottom_part.content, ft.Column):
             bottom_part.content = ft.Column(
                [],
                expand=True,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.START,
                scroll=ft.ScrollMode.AUTO
            )
        
        bottom_part.content.controls.clear()
        for player in players:
            name_text = ft.Text(player.name, size=16)
            name_container = ft.Container(
                content=name_text,
                width=200,
                height=40,
                border_radius=20,
                alignment=ft.alignment.center,
                padding=10,
            )
            detector = ft.GestureDetector(
                content=name_container,
                on_tap=lambda e_tap: edit_name(e_tap) if edit_mode else None,
                on_secondary_tap_down=lambda e_tap: direct_delete(e_tap) if edit_mode else None,
            )
            bottom_part.content.controls.append(ft.Row([detector], alignment=ft.MainAxisAlignment.CENTER))
        page.update()

    def add_name(e):
        if tournament_running:
            return
        value = nome_input.value
        lines = [line.strip() for line in value.split('\n') if line.strip()]
        
        if not isinstance(bottom_part.content, ft.Column):
             rebuild_list()

        for line in lines:
            player = Player(player_id_counter[0], line)
            player_id_counter[0] += 1
            players.append(player)
            name_text = ft.Text(line, size=16)
            name_container = ft.Container(
                content=name_text,
                width=200,
                height=40,
                border_radius=20,
                alignment=ft.alignment.center,
                padding=10,
            )
            detector = ft.GestureDetector(
                content=name_container,
                on_tap=lambda e_tap: edit_name(e_tap) if edit_mode else None,
                on_secondary_tap_down=lambda e_tap: direct_delete(e_tap) if edit_mode else None,
            )
            bottom_part.content.controls.append(ft.Row([detector], alignment=ft.MainAxisAlignment.CENTER))
        nome_input.value = ""
        apply_theme(None)
        nome_input.focus()
        page.update()

    def update_all():
        for match in all_matches:
            if match.update_func:
                match.update_func()
        page.update()

    def seed(n):
        if n == 0:
            return []
        ol = [1]
        for i in range(math.ceil(math.log2(n))):
            l = 2 * len(ol) + 1
            ol = [e if e <= n else 0 for s in [[el, l - el] for el in ol] for e in s]
        return ol

    def start_tournament(e):
        nonlocal tournament_running, bracket_row, tournament_bracket_container, base_bracket_width, base_bracket_height
        if len(players) == 0:
            dlg = ft.AlertDialog(
                title=ft.Text("Erro"),
                content=ft.Text("Número de participantes deve ser maior que 0."),
            )
            page.dialog = dlg
            dlg.open = True
            page.update()
            return

        include_third = third_place_checkbox.value

        tournament_running = True
        connector_canvases.clear()
        all_matches.clear()
        random.shuffle(players)
        num_players = len(players)
        
        bottom_part.content = ft.Container() # placeholder temporario
        third_place_rectangle[0] = None  # reset ref

        depth = math.ceil(math.log2(num_players))
        total_slots = 2 ** depth
        
        seed_order = seed(num_players)
        player_objects = [None if s == 0 else players[s - 1] for s in seed_order]

        leaf_matches = []
        for i in range(0, total_slots, 2):
            p1 = player_objects[i]
            p2 = player_objects[i + 1] if i + 1 < len(player_objects) else None
            m = Match(p1, p2)
            leaf_matches.append(m)
            all_matches.append(m)

        rounds_list = [leaf_matches]
        current = leaf_matches
        while len(current) > 1:
            new_level = []
            for i in range(0, len(current), 2):
                previous2 = current[i + 1] if i + 1 < len(current) else None
                m = Match(previous1=current[i], previous2=previous2)
                new_level.append(m)
                all_matches.append(m)
            rounds_list.append(new_level)
            current = new_level

        champion_match = Match(previous1=current[0], is_champion_slot=True)
        all_matches.append(champion_match)
        rounds_list.append([champion_match])

        third_place_match = None
        if include_third and len(rounds_list) >= 3:
            semifinal_matches = rounds_list[-3]
            if len(semifinal_matches) >= 2:
                third_place_match = Match(previous1=semifinal_matches[0], previous2=semifinal_matches[1], use_losers=True, is_champion_slot=False, set_parent=False)
                all_matches.append(third_place_match)

        for i, m in enumerate(all_matches):
            m.id = i

        rounds_list_global["value"] = rounds_list
        third_place_match_global["value"] = third_place_match
        champion_match_global["value"] = champion_match

        round_col_width = 200
        fixed_box_width = 220
        num_rounds = len(rounds_list)
        
        total_width = num_rounds * round_col_width + max(0, num_rounds - 1) * connector_width
        if third_place_match:
            total_width += connector_width + fixed_box_width
        total_width += 80
        
        base_bracket_width = total_width

        base_match_height = 90
        num_first_round_matches = len(rounds_list[0])
        calculated_height = (num_first_round_matches * base_match_height) + (max(0, num_first_round_matches - 1) * base_spacing)
        calculated_height += 100 
        base_bracket_height = max(calculated_height, 600)

        bracket_row = ft.Row(
            spacing=0, 
            alignment=ft.MainAxisAlignment.START, 
            vertical_alignment=ft.CrossAxisAlignment.START
        )

        tournament_bracket_container = ft.Container(
            content=ft.Container(),
            width=base_bracket_width,
            height=base_bracket_height,
            padding=ft.padding.only(10),
        )

        outer_scroll_column = ft.Column(
            [tournament_bracket_container],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            alignment=ft.MainAxisAlignment.START,
            horizontal_alignment=ft.CrossAxisAlignment.START
        )

        bottom_part.content = outer_scroll_column

        tournament_bracket_container.data = {
            "base_round_col_width": round_col_width,
            "base_fixed_box_width": fixed_box_width,
            "base_connector_width": connector_width,
            "base_match_height": base_match_height,
            "base_spacing": base_spacing,
            "num_rounds": num_rounds,
        }

        apply_transform()
        page.update()

    def render_bracket(scale: float):
        nonlocal connector_canvases, third_place_rectangle

        rounds_list = rounds_list_global["value"]
        if rounds_list is None:
            return

        connector_canvases.clear()

        container = tournament_bracket_container
        base_metrics = container.data
        round_col_width = int(base_metrics["base_round_col_width"] * scale)
        fixed_box_width = int(base_metrics["base_fixed_box_width"] * scale)
        connector_w = int(base_metrics["base_connector_width"] * scale)
        base_match_height = int(base_metrics["base_match_height"] * scale)
        spacing = int(base_metrics["base_spacing"] * scale)
        num_rounds = base_metrics["num_rounds"]

        slot_heights = []
        current_height = base_match_height
        slot_heights.append(current_height)
        for _ in range(1, len(rounds_list) - 1):
            current_height = current_height * 2 + spacing
            slot_heights.append(current_height)
        if len(rounds_list) > 1:
            slot_heights.append(current_height)

        total_width = num_rounds * round_col_width + max(0, num_rounds - 1) * connector_w
        if third_place_match_global["value"]:
            total_width += connector_w + fixed_box_width
        total_width += int(80 * scale)

        total_height = max(int((len(rounds_list[0]) * base_match_height) + ((len(rounds_list[0]) - 1) * spacing) + 100 * scale), int(600 * scale))

        bracket_row = ft.Row(
            spacing=0,
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.START
        )

        inner_scroll_row = ft.Row([bracket_row], scroll=ft.ScrollMode.AUTO, expand=True)

        for level, round_matches in enumerate(rounds_list):
            label = get_elim_round_label(len(round_matches), level, num_rounds)

            header = ft.Text(label, size=int(18 * scale), weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER)
            round_column = ft.Column(spacing=spacing, alignment=ft.MainAxisAlignment.START, expand=True)
            round_column.controls.append(header)

            if level > 0:
                connector_col = ft.Column(spacing=spacing, alignment=ft.MainAxisAlignment.START, expand=True)
                connector_col.controls.append(ft.Text("", size=int(18 * scale)))

                paint = ft.Paint(
                    color=theme_vars.get('line_color', ft.Colors.BLACK),
                    stroke_width=max(1, int(2 * scale)),
                    style=ft.PaintingStyle.STROKE,
                )

                for match in round_matches:
                    if match.previous2 is None:
                        center_y = slot_heights[level] / 2
                        elements = [
                            cv.Path.MoveTo(0, center_y),
                            cv.Path.LineTo(connector_w, center_y),
                        ]
                        shapes = [cv.Path(elements=elements, paint=paint)]
                    else:
                        prev_height = slot_heights[level - 1]
                        rel_top = prev_height / 2
                        rel_bottom = rel_top + prev_height + spacing
                        half_w = connector_w / 2
                        radius = max(4, int(10 * scale))

                        bracket_elements = [
                            cv.Path.MoveTo(0, rel_top),
                            cv.Path.LineTo(half_w - radius, rel_top),
                            cv.Path.QuadraticTo(half_w, rel_top, half_w, rel_top + radius),
                            cv.Path.LineTo(half_w, rel_bottom - radius),
                            cv.Path.QuadraticTo(half_w, rel_bottom, half_w - radius, rel_bottom),
                            cv.Path.LineTo(0, rel_bottom),
                        ]

                        middle_elements = [
                            cv.Path.MoveTo(half_w, (rel_top + rel_bottom) / 2),
                            cv.Path.LineTo(connector_w, (rel_top + rel_bottom) / 2),
                        ]

                        shapes = [
                            cv.Path(elements=bracket_elements, paint=paint),
                            cv.Path(elements=middle_elements, paint=paint),
                        ]

                    canvas = cv.Canvas(
                        shapes=shapes,
                        width=connector_w,
                        height=int(slot_heights[level]),
                    )
                    connector_canvases.append(canvas)
                    padded = ft.Container(
                        content=canvas,
                        height=int(slot_heights[level]),
                        alignment=ft.alignment.top_left,
                    )
                    connector_col.controls.append(padded)

                bracket_row.controls.append(ft.Container(content=connector_col, width=connector_w))

            for match in round_matches:
                match_widget = create_match_widget(match, scale=scale)
                padded = ft.Container(
                    content=match_widget,
                    height=int(slot_heights[level]),
                    alignment=ft.alignment.center,
                )
                round_column.controls.append(padded)
            bracket_row.controls.append(ft.Container(content=round_column, width=round_col_width))

        third_place_match = third_place_match_global["value"]
        if third_place_match:
            bracket_row.controls.append(ft.Container(width=connector_w))

            header = ft.Text("3º Lugar", size=int(16 * scale), weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER)

            box_bg = theme_vars.get('tbd_bg', ft.Colors.GREY_200)
            box_border = theme_vars.get('line_color', ft.Colors.BLACK)

            champion_slot_height = slot_heights[-1] if len(slot_heights) > 0 else base_match_height
            third_place_height = int(base_match_height * 2 + spacing)
            third_place_height = max(third_place_height, int(champion_slot_height))
            rectangle = ft.Container(
                content=ft.Column([], alignment=ft.MainAxisAlignment.CENTER),
                width=fixed_box_width,
                height=third_place_height,
                border_radius=8,
                border=ft.border.all(max(1, int(2 * scale)), box_border),
                bgcolor=box_bg,
                alignment=ft.alignment.center,
                padding=10,
            )

            match_widget = create_match_widget(third_place_match, scale=scale)
            inner_match_padded = ft.Container(
                content=match_widget,
                height=int(base_match_height),
                alignment=ft.alignment.center,
            )

            rectangle.content.controls.append(inner_match_padded)

            third_col = ft.Column(spacing=int(10 * scale), alignment=ft.MainAxisAlignment.START)
            third_col.controls.append(header)
            third_col.controls.append(rectangle)

            third_place_rectangle[0] = rectangle

            bracket_row.controls.append(ft.Container(content=third_col, width=fixed_box_width))

        tournament_bracket_container.content = inner_scroll_row

        for canvas in connector_canvases:
            for shape in canvas.shapes:
                shape.paint.color = theme_vars.get('line_color', ft.Colors.BLACK)

        if third_place_rectangle[0] is not None:
            rect = third_place_rectangle[0]
            rect.border = ft.border.all(2, theme_vars.get('line_color', ft.Colors.BLACK))
            rect.bgcolor = theme_vars.get('tbd_bg', ft.Colors.GREY_200)

        update_all()

    def create_match_widget(match, scale: float = 1.0):
        has_p1_side = match.player1 is not None or match.previous1 is not None
        has_p2_side = match.player2 is not None or match.previous2 is not None

        p1 = match.get_player1()
        p2 = match.get_player2()

        text_size = max(6, int(14 * scale))
        cont_width = max(60, int(150 * scale))
        cont_height = max(20, int(40 * scale))  # Fixed height to ensure same size
        padding_value = max(2, int(10 * scale))

        match_widget_controls = []

        if has_p1_side:
            p1_text = ft.Text(p1.name if p1 else "", size=text_size, text_align=ft.TextAlign.CENTER)
            p1_container = ft.Container(content=p1_text, width=cont_width, height=cont_height, padding=ft.padding.all(padding_value), border_radius=20, alignment=ft.alignment.center)
            p1_container.data = {'player': p1, 'match_id': match.id} if p1 else None

            def edit_p1(e):
                if not edit_mode or p1 is None:
                    return

                def confirm_p1(e):
                    new_name = e.control.value.strip()
                    p1_container.content = p1_text
                    if new_name:
                        p1.name = new_name
                        update_all()
                    else:
                        page.update()

                def cancel_p1(e):
                    p1_container.content = p1_text
                    page.update()

                edit_field = ft.TextField(
                    value=p1.name,
                    width=cont_width,
                    height=cont_height,
                    border_radius=20,
                    content_padding=padding_value,
                    text_align=ft.TextAlign.CENTER,
                    border_width=0,
                    on_submit=confirm_p1,
                    on_blur=cancel_p1
                )
                p1_container.content = edit_field
                page.update()
                edit_field.focus()

            def double_tap_p1(e):
                if match.winner is None and p1 and p2:
                    match.p1_series += 1
                    if match.p1_series >= math.ceil(match.best_of / 2):
                        match.winner = p1
                    update_all()

            p1_gesture = ft.GestureDetector(
                content=p1_container,
                on_tap=edit_p1,
                on_double_tap=double_tap_p1
            )

            def start_drag_p1(e):
                dragging[0] = p1_container.data

            p1_draggable = ft.Draggable(
                group="player",
                content=p1_gesture,
                disabled=p1 is None or match.winner is not None,
                on_drag_start=start_drag_p1
            )
            p1_target = ft.DragTarget(
                group="player",
                content=p1_draggable,
                on_will_accept=lambda e: combined_will_accept(e, match, is_p1=True),
                on_accept=lambda e: combined_accept(e, match, is_p1=True),
                on_leave=lambda e: combined_leave(e, match, is_p1=True),
            )
            match_widget_controls.append(p1_target)

        if has_p2_side:
            p2_text = ft.Text(p2.name if p2 else "", size=text_size, text_align=ft.TextAlign.CENTER)
            p2_container = ft.Container(content=p2_text, width=cont_width, height=cont_height, padding=ft.padding.all(padding_value), border_radius=20, alignment=ft.alignment.center)
            p2_container.data = {'player': p2, 'match_id': match.id} if p2 else None

            def edit_p2(e):
                if not edit_mode or p2 is None:
                    return

                def confirm_p2(e):
                    new_name = e.control.value.strip()
                    p2_container.content = p2_text
                    if new_name:
                        p2.name = new_name
                        update_all()
                    else:
                        page.update()

                def cancel_p2(e):
                    p2_container.content = p2_text
                    page.update()

                edit_field = ft.TextField(
                    value=p2.name,
                    width=cont_width,
                    height=cont_height,
                    border_radius=20,
                    content_padding=padding_value,
                    text_align=ft.TextAlign.CENTER,
                    border_width=0,
                    on_submit=confirm_p2,
                    on_blur=cancel_p2
                )
                p2_container.content = edit_field
                page.update()
                edit_field.focus()

            def double_tap_p2(e):
                if match.winner is None and p1 and p2:
                    match.p2_series += 1
                    if match.p2_series >= math.ceil(match.best_of / 2):
                        match.winner = p2
                    update_all()

            p2_gesture = ft.GestureDetector(
                content=p2_container,
                on_tap=edit_p2,
                on_double_tap=double_tap_p2
            )

            def start_drag_p2(e):
                dragging[0] = p2_container.data

            p2_draggable = ft.Draggable(
                group="player",
                content=p2_gesture,
                disabled=p2 is None or match.winner is not None,
                on_drag_start=start_drag_p2
            )
            p2_target = ft.DragTarget(
                group="player",
                content=p2_draggable,
                on_will_accept=lambda e: combined_will_accept(e, match, is_p1=False),
                on_accept=lambda e: combined_accept(e, match, is_p1=False),
                on_leave=lambda e: combined_leave(e, match, is_p1=False),
            )
            match_widget_controls.append(p2_target)

        if len(match_widget_controls) == 2:
            match_widget = ft.Column(
                match_widget_controls,
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=max(6, int(10 * scale)),
            )
        elif len(match_widget_controls) == 1:
            match_widget = match_widget_controls[0]
        else:
            match_widget = ft.Text("Error")

        def update_func():
            nonlocal p1, p2
            p1 = match.get_player1()
            p2 = match.get_player2()

            name_color = theme_vars.get('name_color', '#000000')
            name_bg = theme_vars.get('name_bg', '#FFFFFF')
            name_border = theme_vars.get('name_border', None)
            tbd_color = theme_vars.get('tbd_color', ft.Colors.GREY)
            tbd_bg = theme_vars.get('tbd_bg', ft.Colors.GREY_200)

            if has_p1_side:
                p1_text.value = p1.name if p1 else ""
                p1_container.data = {'player': p1, 'match_id': match.id} if p1 else None

                if p1 is None:
                    p1_text.color = tbd_color
                    p1_container.bgcolor = tbd_bg
                else:
                    if match.winner == p1:
                        p1_container.bgcolor = ft.Colors.GREEN
                        p1_text.color = ft.Colors.WHITE
                    elif match.winner is not None:
                        p1_container.bgcolor = ft.Colors.RED
                        p1_text.color = ft.Colors.WHITE
                    else:
                        p1_container.bgcolor = name_bg
                        if not has_p2_side:
                            p1_text.color = ft.Colors.GREEN
                        else:
                            p1_text.color = name_color

                p1_container.border = name_border
                p1_draggable.disabled = p1 is None or match.winner is not None

            if has_p2_side:
                p2_text.value = p2.name if p2 else ""
                p2_container.data = {'player': p2, 'match_id': match.id} if p2 else None

                if p2 is None:
                    p2_text.color = tbd_color
                    p2_container.bgcolor = tbd_bg
                else:
                    if match.winner == p2:
                        p2_container.bgcolor = ft.Colors.GREEN
                        p2_text.color = ft.Colors.WHITE
                    elif match.winner is not None:
                        p2_container.bgcolor = ft.Colors.RED
                        p2_text.color = ft.Colors.WHITE
                    else:
                        p2_container.bgcolor = name_bg
                        if not has_p1_side:
                            p2_text.color = ft.Colors.GREEN
                        else:
                            p2_text.color = name_color

                p2_container.border = name_border
                p2_draggable.disabled = p2 is None or match.winner is not None

            if getattr(match, "is_champion_slot", False):
                champ_player = p1
                if champ_player and not match._had_winner:
                    match._had_winner = True
                    page.run_task(trigger_confetti)
                elif not champ_player:
                    match._had_winner = False

        match.update_func = update_func

        update_func()

        return match_widget

    def combined_will_accept(e, match, is_p1):
        source_data = dragging[0]
        if source_data is None:
            return False

        try:
            container = e.control.content.content.content
        except Exception:
            container = None

        if match.parent and source_data['match_id'] == match.parent.id and match.winner is not None:
            if container is not None:
                container.border = ft.border.all(2, ft.Colors.RED)
                e.control.update()
            return True

        if (is_p1 and match.get_player1() is not None) or (not is_p1 and match.get_player2() is not None):
            return False
        previous = match.previous1 if is_p1 else match.previous2
        if previous is None:
            return False
        if source_data['match_id'] != previous.id:
            return False
        if source_data['player'] != previous.get_player1() and source_data['player'] != previous.get_player2():
            return False
        if container is not None:
            container.border = ft.border.all(2, ft.Colors.BLACK)
            e.control.update()
        return True

    def combined_accept(e, match, is_p1):
        source_data = dragging[0]
        if source_data is None:
            return

        if match.parent and source_data['match_id'] == match.parent.id:
            match.winner = None
            update_all()
            return

        previous = match.previous1 if is_p1 else match.previous2
        if previous and previous.id == source_data['match_id']:
            previous.winner = source_data['player']
            update_all()

    def combined_leave(e, match, is_p1):
        try:
            container = e.control.content.content.content
            container.border = theme_vars.get('name_border', None)
            e.control.update()
        except Exception:
            pass

    nome_input = ft.TextField(
        label="Digite nomes aqui",
        hint_text="Ex: Nome1, Nome2, ...",
        width=400,
        border_radius=10,
        multiline=True,
        shift_enter=True,
        on_submit=add_name,
    )

    theme_dropdown = ft.Dropdown(
        label="Tema",
        options=[ft.dropdown.Option(t) for t in ["Branco", "Preto", "Ciano", "Roxo", "Neon", "Vermelho", "Carmesin", "Midnight Galaxy", "Blush Dawn", "Void Amethyst"]],
        value="Preto",
        width=200,
    )

    def apply_theme(e):
        theme = theme_dropdown.value
        gradient = None
        dropdown_border = None
        name_bg = '#FFFFFF'
        name_color = '#000000'
        name_border = ft.border.all(1, '#000000')
        tbd_bg = ft.Colors.GREY_200
        tbd_color = ft.Colors.GREY
        line_color = ft.Colors.BLACK
        container_bg = '#FFFFFF'
        button_bg = '#E0E0E0'
        button_color = '#000000'
        input_bg = '#F5F5F5'
        input_border = '#CCCCCC'
        shadow_color = ft.Colors.with_opacity(0.2, '#000000')
        button_gradient = None
        
        if theme == "Branco":
            page.theme_mode = ft.ThemeMode.LIGHT
            page_bg = '#FFFFFF'
            container_bg = '#FFFFFF'
            shadow_color = ft.Colors.with_opacity(0.2, '#000000')
            button_bg = '#E0E0E0'
            button_color = '#000000'
            input_bg = '#F5F5F5'
            input_border = '#CCCCCC'
            name_border = ft.border.all(1, '#000000')
            tbd_bg = ft.Colors.GREY_200
            tbd_color = ft.Colors.GREY
        elif theme == "Preto":
            page.theme_mode = ft.ThemeMode.DARK
            page_bg = '#0F1115'
            container_bg = '#181B21'
            shadow_color = ft.Colors.with_opacity(0.1, '#000000')
            button_bg = '#20242C'
            button_color = '#E6E8EB'
            input_bg = '#181B21'
            input_border = '#2A2F3A'
            dropdown_border = '#2A2F3A'
            name_bg = '#20242C'
            name_color = '#E6E8EB'
            name_border = ft.border.all(1, "#9E9E9E")
            tbd_bg = ft.Colors.BLUE_GREY_900
            tbd_color = ft.Colors.BLUE_GREY_400
            line_color = ft.Colors.GREY_300
        elif theme == "Ciano":
            page.theme_mode = ft.ThemeMode.LIGHT
            gradient = ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=["#E0FFFF", "#A7E9FF", "#5DD8FF"]
            )
            container_bg = "#D0F5FF"
            shadow_color = ft.Colors.with_opacity(0.3, "#00BCD4")
            button_bg = "#5DD8FF"
            button_color = "#003E47"
            input_bg = "#C8F0FF"
            input_border = "#00BCD4"
            dropdown_border = "#00BCD4"
            name_bg = "#C8F0FF"
            name_color = "#003E47"
            name_border = ft.border.all(1, "#00BCD4")
            tbd_bg = "#D0F5FF"
            tbd_color = "#005C63"
            line_color = "#00BCD4"
            button_gradient = ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=["#00E5FF", "#00BCD4"]
            )
        elif theme == "Roxo":
            page.theme_mode = ft.ThemeMode.DARK
            gradient = ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=["#2e1a47", "#4b2f76", "#6a46a5"]
            )
            container_bg = "#3b2261"
            shadow_color = ft.Colors.with_opacity(0.3, "#b892ff")
            button_bg = "#6a46a5"
            button_color = "#FFFFFF"
            input_bg = "#3b2261"
            input_border = "#b892ff"
            dropdown_border = "#c5a3ff"
            name_bg = "#4b2f76"
            name_color = "#FFFFFF"
            name_border = ft.border.all(1, "#c5a3ff")
            tbd_bg = "#4b2f76"
            tbd_color = "#d8b9ff"
            line_color = "#b892ff"
            button_gradient = ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=["#b892ff", "#6a46a5"]
            )
        elif theme == "Neon":
            page.theme_mode = ft.ThemeMode.DARK
            gradient = ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=["#001100", "#003322", "#00FF88"]
            )
            container_bg = "#002A1A"
            shadow_color = ft.Colors.with_opacity(0.4, "#00FFAA")
            button_bg = "#004D33"
            button_color = "#00FFAA"
            input_bg = "#002A1A"
            input_border = "#00FF88"
            dropdown_border = "#00FFAA"
            name_bg = "#003322"
            name_color = "#00FFAA"
            name_border = ft.border.all(1, "#00FFAA")
            tbd_bg = "#001A0F"
            tbd_color = "#00CC77"
            line_color = "#00FF88"
            button_gradient = ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=["#00FFAA", "#00CC66"]
            )
        elif theme == "Vermelho":
            page.theme_mode = ft.ThemeMode.LIGHT
            gradient = ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=["#ffdddd", "#ffbbbb", "#ff9999"]
            )
            container_bg = "#ffdddd"
            shadow_color = ft.Colors.with_opacity(0.2, "#ff9999")
            button_bg = "#ff9999"
            button_color = "#800000"
            input_bg = "#ffcccc"
            input_border = "#ff7777"
            dropdown_border = "#ff6666"
            name_bg = "#ffbbbb"
            name_color = "#800000"
            name_border = ft.border.all(1, "#ff6666")
            tbd_bg = "#ffcccc"
            tbd_color = "#cc0000"
            line_color = "#ff6666"
            button_gradient = ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=["#ffaaaa", "#ff8888"]
            )
        elif theme == "Carmesin":
            page.theme_mode = ft.ThemeMode.DARK
            gradient = ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=["#0A0000", "#330000", "#8B0000"]
            )
            container_bg = "#1A0000"
            shadow_color = ft.Colors.with_opacity(0.3, "#FF4444")
            button_bg = "#8B0000"
            button_color = "#FFFFFF"
            input_bg = "#220000"
            input_border = "#B22222"
            dropdown_border = "#FF5555"
            name_bg = "#220000"
            name_color = "#FFFFFF"
            name_border = ft.border.all(1, "#FF5555")
            tbd_bg = "#400000"
            tbd_color = "#FF8888"
            line_color = "#FF3B3B"
            button_gradient = ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=["#FF5555", "#8B0000"]
            )
        elif theme == "Midnight Galaxy":
            page.theme_mode = ft.ThemeMode.DARK
            gradient = ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=["#0a0f2c", "#1b204a", "#243b6b"]
            )
            container_bg = "#0d132b"
            shadow_color = ft.Colors.with_opacity(0.3, "#3b4cc0")
            button_bg = "#243b6b"
            button_color = "#FFFFFF"
            input_bg = "#14193a"
            input_border = "#3b4cc0"
            dropdown_border = "#4b5fc7"
            name_bg = "#1b204a"
            name_color = "#FFFFFF"
            name_border = ft.border.all(1, "#4b5fc7")
            tbd_bg = "#1b204a"
            tbd_color = "#6c8ef5"
            line_color = "#3b4cc0"
            button_gradient = ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=["#3b4cc0", "#243b6b"]
            )
        elif theme == "Blush Dawn":
            page.theme_mode = ft.ThemeMode.LIGHT
            gradient = ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=["#FFE1EE", "#F9BFD7", "#F8A3C8"]
            )
            container_bg = "#F5CFE0"
            shadow_color = ft.Colors.with_opacity(0.25, "#FF7EB9")
            button_bg = "#F8DDE8"
            button_color = "#2D1F29"
            input_bg = "#F5CFE0"
            input_border = "#5E4A55"
            name_bg = "#F5CFE0"
            name_color = "#2D1F29"
            name_border = ft.border.all(1, "#5E4A55")
            tbd_bg = "#F8DDE8"
            tbd_color = "#5E4A55"
            line_color = "#FF7EB9"
            button_gradient = ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=["#FFB4DC", "#FF7EB9"]
            )
        elif theme == "Void Amethyst":
            page.theme_mode = ft.ThemeMode.DARK
            gradient = ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=["#10051E", "#20124A", "#381A70"]
            )
            container_bg = "#231B3B"
            shadow_color = ft.Colors.with_opacity(0.3, "#A855F7")
            button_bg = "#1A162B"
            button_color = "#E6E0FF"
            input_bg = "#231B3B"
            input_border = "#A59FCF"
            dropdown_border = "#A59FCF"
            name_bg = "#231B3B"
            name_color = "#E6E0FF"
            name_border = ft.border.all(1, "#A59FCF")
            tbd_bg = "#1A162B"
            tbd_color = "#A59FCF"
            line_color = "#A855F7"
            button_gradient = ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=["#C084FC", "#9333EA"]
            )

        theme_vars['name_bg'] = name_bg
        theme_vars['name_color'] = name_color
        theme_vars['name_border'] = name_border
        theme_vars['tbd_bg'] = tbd_bg
        theme_vars['tbd_color'] = tbd_color
        theme_vars['line_color'] = line_color
        theme_vars['page_bg'] = locals().get('page_bg', '#000000')

        main_container.bgcolor = locals().get('page_bg', '#FFFFFF') if gradient is None else None
        main_container.gradient = gradient
        page.bgcolor = ft.Colors.TRANSPARENT
        top_part.bgcolor = container_bg
        bottom_part.bgcolor = ft.Colors.TRANSPARENT
        top_part.shadow = ft.BoxShadow(blur_radius=10, color=shadow_color)
        bottom_part.shadow = None
        for btn in buttons:
            if btn == edit_button and edit_mode:
                btn.bgcolor = '#FFFF00'
                btn.color = '#000000'
            else:
                btn.bgcolor = button_bg if button_gradient is None else None
                btn.gradient = button_gradient
                btn.color = button_color
        nome_input.bgcolor = input_bg
        nome_input.border_color = input_border
        if dropdown_border:
            theme_dropdown.border_color = dropdown_border
        else:
            theme_dropdown.border_color = None

        if tournament_running:
            update_all()
            for canvas in connector_canvases:
                for shape in canvas.shapes:
                    shape.paint.color = line_color

            rect = third_place_rectangle[0]
            if rect is not None:
                rect.border = ft.border.all(2, line_color)
                rect.bgcolor = tbd_bg
        else:
            if isinstance(bottom_part.content, ft.Column):
                 for row in bottom_part.content.controls:
                    if isinstance(row, ft.Row) and row.controls:
                        detector = row.controls[0]
                        container = detector.content
                        container.bgcolor = name_bg
                        container.border = name_border
                        content = container.content
                        if isinstance(content, ft.Text):
                            content.color = name_color
                        elif isinstance(content, ft.TextField):
                            content.color = name_color
                            content.bgcolor = ft.Colors.TRANSPARENT

        tutorial_inner.bgcolor = container_bg
        text_color = name_color
        icon_color = button_color
        example_container.bgcolor = input_bg
        example_text.color = text_color
        close_button.icon_color = icon_color
        title_text.color = text_color
        for ctrl in tutorial_column.controls:
            if isinstance(ctrl, ft.Text):
                ctrl.color = text_color
            elif isinstance(ctrl, ft.Container):
                ctrl.content.color = text_color

        page.update()
        apply_transform()

    theme_dropdown.on_change = apply_theme

    top_part = ft.Container(
        content=ft.Column(
            [
                ft.Row([theme_dropdown, third_place_checkbox], alignment=ft.MainAxisAlignment.CENTER),
                ft.Row([nome_input], alignment=ft.MainAxisAlignment.CENTER),
                ft.Row(buttons, alignment=ft.MainAxisAlignment.CENTER, spacing=10),
            ],
            spacing=10,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        height=200,
        border_radius=15,
        padding=20,
        shadow=ft.BoxShadow(blur_radius=10),
    )

    bottom_part = ft.Container(
        content=ft.Column(
            [],
            expand=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.START,
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
        border_radius=15,
        padding=20,
    )

    main_container = ft.Container(
        expand=True,
        content=ft.Stack(
            [
                ft.Column(
                    [
                        top_part,
                        bottom_part,
                    ],
                    spacing=0,
                    expand=True,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
                overlay,
            ]
        ),
    )

    page.add(main_container)

    title_text = ft.Text("🧠 Como usar:", size=18, weight=ft.FontWeight.BOLD)
    close_button = ft.IconButton(ft.Icons.CLOSE, on_click=lambda e: close_tutorial(e))
    example_text = ft.Text("Lucas\nMariana\nJoão\nBeatriz", font_family="monospace", size=14)
    example_container = ft.Container(
        content=example_text,
        padding=10,
        border_radius=5,
    )
    tutorial_column = ft.Column([
        ft.Row([
            title_text,
            close_button,
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ft.Text("● 🎨 Temas", size=16, weight=ft.FontWeight.BOLD),
        ft.Text(" ⚬ Personalize o visual do app escolhendo o tema de sua preferência."),
        ft.Text("● 👤 Digitar Participantes", size=16, weight=ft.FontWeight.BOLD),
        ft.Text(" ⚬ Você pode adicionar nomes um por um, pressionando Enter após cada um."),
        ft.Text(" ⚬ Ou colar vários nomes de uma vez, desde que cada um esteja em linhas separadas (não “parágrafos”)."),
        ft.Text(" ⚬ Exemplo:"),
        example_container,
        ft.Text("● 🏁 Botão Iniciar", size=16, weight=ft.FontWeight.BOLD),
        ft.Text(" ⚬ Inicia o torneio eliminatório, criando automaticamente os confrontos, semifinais e final, até definir o campeão."),
        ft.Text("● 🎲 Botão Randomizar", size=16, weight=ft.FontWeight.BOLD),
        ft.Text(" ⚬ Mistura completamente a ordem dos participantes, criando novas combinações aleatórias a cada clique."),
        ft.Text("● ✏️ Botão Editar", size=16, weight=ft.FontWeight.BOLD),
        ft.Text(" ⚬ Clique esquerdo sobre um nome → editar e pressionar Enter para confirmar."),
        ft.Text(" ⚬ Clique direito → apagar o participante (disponível antes de iniciar o torneio ou após voltar ao modo de edição)."),
        ft.Text("● 🔁 Botão Resetar", size=16, weight=ft.FontWeight.BOLD),
        ft.Text(" ⚬ Remove todos os participantes e reinicia o torneio do zero."),
        ft.Text("● ⏪ Botão “Voltar para Edição”", size=16, weight=ft.FontWeight.BOLD),
        ft.Text(" ⚬ Retorna à tela inicial para editar ou adicionar novos participantes antes de reiniciar o torneio."),
        ft.Text("● 🏆 Progressão pelo Torneio", size=16, weight=ft.FontWeight.BOLD),
        ft.Text(" ⚬ Dois cliques sobre um participante → avança ele para o próximo round."),
        ft.Text(" ⚬ Arrastar e soltar → move o participante para outro slot (mesmo sem oponente, propositalmente)."),
        ft.Text(" ⚬ Arrastar para trás → reverte o resultado do confronto anterior."),
        ft.Text("● 🔍 Zoom e Scroll", size=16, weight=ft.FontWeight.BOLD),
        ft.Text(" ⚬ Use os botões de lupa ou Ctrl + Roda do Mouse para dar zoom."),
        ft.Text(" ⚬ O scroll vertical e horizontal se ajusta automaticamente ao tamanho do bracket."),
    ], scroll=ft.ScrollMode.AUTO)
    tutorial_inner = ft.Container(
        width=400,
        border_radius=10,
        padding=20,
        content=tutorial_column,
    )

    tutorial_detector = ft.GestureDetector(
        content=tutorial_inner,
        on_tap=lambda e: None,
    )

    tutorial_overlay = ft.Container(
        expand=True,
        bgcolor=ft.Colors.with_opacity(0.5, ft.Colors.BLACK),
        alignment=ft.alignment.center,
        visible=False,
        offset=ft.Offset(1, 0),
        animate_offset=ft.Animation(duration=400, curve=ft.AnimationCurve.EASE_IN_OUT),
        content=tutorial_detector,
        on_click=lambda e: close_tutorial(e),
    )

    page.overlay.append(tutorial_overlay)

    def show_tutorial(e):
        tutorial_overlay.visible = True
        tutorial_overlay.offset = ft.Offset(0, 0)
        page.update()

    async def hide_tutorial():
        await asyncio.sleep(0.4)
        tutorial_overlay.visible = False
        page.update()

    def close_tutorial(e):
        tutorial_overlay.offset = ft.Offset(1, 0)
        tutorial_overlay.update()
        page.run_task(hide_tutorial)

    apply_theme(None)

ft.app(target=main, assets_dir="assets")
