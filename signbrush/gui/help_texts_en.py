"""English texts of the (i) hints, same keys as :data:`help_texts.HELP`."""


def _h(title, group, text, tip, default, impact, kind=""):
    d = {"title": title, "group": group, "text": text, "tip": tip, "def": default, "impact": impact}
    if kind:
        d["impactKind"] = kind
    return d


_SIGN, _IMG, _BRUSH, _SPEED = "Sign & calibration", "Image", "Brush", "Speed & reliability"
_PIX = "Image · “Pixels” only"

HELP_EN: dict[str, dict[str, str]] = {
    'profile': _h('Calibration profile', _SIGN,
                  'A profile stores the layout of the game UI for one screen resolution and UI scale. New monitor or '
                  'resolution — create a new profile with “+”: it starts as a copy of the current one.',
                  'Name profiles after the resolution: “2560×1440”, “1920×1080 laptop”.',
                  'by screen resolution', 'Cannot paint without a profile', 'warn'),
    'signType': _h('Sign type', _SIGN,
                   'Sets the canvas proportions and resolution, which define the picture grid: an XL Picture Frame is '
                   '256×256 at 2 px detail. “From the canvas on screen (auto)” takes the size from the calibration.',
                   'Hover an item in the list to see what the sign looks like in the game.',
                   'from the canvas (auto)', 'Changes the grid and the time'),
    'customSize': _h('Custom size', _SIGN,
                     'Canvas resolution in texture pixels, “width x height”. Only used by the “Custom” type — e.g. for '
                     'signs that are not in the list yet.',
                     'Use multiples of the detail: at 2 px, 512x256 gives a 256×128 grid.',
                     '512x256', 'Custom only'),
    'paletteGrid': _h('Favourites palette', _SIGN,
                      'How many favourite colour cells the game has: columns × rows. The program clicks them instead of '
                      'typing HEX when “Favourite colours” is selected.',
                      'Count the cells in the sign editor and enter the numbers once.',
                      '1 × 3', 'Needed for “Favourites”'),
    'calib': _h('Calibration', _SIGN,
                'You mark once on a screenshot where the canvas, the brush slider, the HEX field and the palette are. '
                'About a minute, 14 guided steps. Repeat only after changing the resolution or the UI scale.',
                'Press A on the first step — the canvas is found automatically.',
                '—', 'Required before the first picture', 'warn'),
    'snapshot': _h('Screenshot in 5 s', _SIGN,
                   'Takes a screenshot after a delay, so you can switch to the game and open the sign editor. The '
                   'calibration then opens on that screenshot.',
                   'Handy when the game is fullscreen and Alt+Tab minimizes it.',
                   '5 s', 'Does not move the mouse', 'ok'),
    'measure': _h('Measure brush', _SIGN,
                  'Paints 2 test dots in a corner of the canvas and measures them on a screenshot, so a picture “pixel” '
                  'matches the in-game brush exactly — no gaps or overlaps. The dots are then erased with Ctrl+Z.',
                  'Measure again after changing the brush size in the game.',
                  '—', 'Without it — risk of gaps', 'warn'),
    'speedtest': _h('Speed test', _SIGN,
                    'Paints 5 corners and 5 dots and checks on a screenshot that all of them landed. This picks the '
                    'shortest pause between actions that the game keeps up with.',
                    'Run it at the same FPS as when painting: with the editor open.',
                    '—', 'Makes painting faster', 'ok'),
    'algo': _h('Algorithm', _IMG,
               '“Hybrid” first covers the canvas with large strokes, then repaints exactly where the colour differs more '
               'than the tolerance. “Pixels” is an exact copy but the slowest. “Strokes only” is fast and painterly.',
               'Start with Hybrid: the best balance of quality and time.',
               'Hybrid', 'Strongly affects time'),
    'strokes': _h('Strokes', _IMG,
                  'How many translucent circles to lay down in the first stage. More strokes — more exact shapes, but '
                  'longer painting.',
                  'For Hybrid 3,000–6,000 is usually enough: the touch-up does the rest.',
                  '1,000 (hybrid) · 6,000 (strokes only)', 'More = slower'),
    'tolerance': _h('Touch-up tolerance, ΔE', _IMG,
                    'How far the colour after the strokes may be from the target before the pixel is repainted exactly. '
                    'ΔE is a perceived colour difference: up to 2 is barely visible, above 10 is clearly another colour.',
                    'Lower tolerance — more exact and slower. 6–10 is a good range.',
                    '8.0 ΔE', 'Lower = slower'),
    'scale': _h('Scaling', _IMG,
                'How to fit the picture when its proportions differ from the sign. “Fit” leaves margins, “Fill” crops the '
                'edges, “Stretch” distorts the proportions.',
                'Portraits and logos — “Fit”, landscapes — “Fill”.',
                'Fit', 'Does not affect time', 'ok'),
    'transparent': _h('Transparent & margins', _IMG,
                      'What to do with transparent pixels and the margins after “Fit”: paint them with the background '
                      'colour or leave them alone — then whatever is already on the sign stays.',
                      '“Do not paint” saves time if you like the sign background.',
                      'Fill with background', '“Do not paint” = faster', 'ok'),
    'bgColor': _h('Background colour', _IMG,
                  'Colour for the margins and transparent areas. Click the swatch to pick a colour, or paste a HEX.',
                  'Take the colour from the edge of the picture — the margins become invisible.',
                  '#FFFFFF', 'Does not affect time', 'ok'),
    'colorInput': _h('Colour input', _IMG,
                     'How the program selects a colour in the game. HEX input gives any colour exactly. The picker clicks '
                     'the colour square. Favourites clicks ready palette cells — fastest, but few colours.',
                     'HEX input is the most reliable default.',
                     'HEX input', 'Affects the colour change pause'),
    'colors': _h('Quality — number of colours', _IMG,
                 'How many different colours remain after simplifying the picture. Every new colour is a colour change in '
                 'the game and extra seconds. 0 — choose automatically.',
                 'For pixel art use the exact number of colours of the original.',
                 '0 = auto', 'More = slower'),
    'dither': _h('Floyd–Steinberg dithering', _PIX,
                 'Mixes neighbouring colours with dots so smooth gradients do not turn into bands. Useful with few colours.',
                 'Photos — on, pixel art and logos — off.',
                 'off', 'Slightly more strokes'),
    'cleanup': _h('Lone-pixel cleanup', _PIX,
                  'Removes “noise” — single pixels unlike their neighbours. The higher the level (0–5), the larger the '
                  'specks treated as noise.',
                  '1–2 is usually enough. Keep it low for fine details (eyes, text).',
                  '1', 'Fewer strokes', 'ok'),
    'detail': _h('Detail', _BRUSH,
                 'Size of one picture “pixel” in sign texture pixels. The main quality/time lever: a pixel twice as big '
                 'means four times fewer strokes.',
                 'Start with 2 px. For a quick draft — 4–8 px.',
                 '2 px', 'Main time lever', 'warn'),
    'fillBrush': _h('Fill brush', _BRUSH,
                    'Large single-colour areas are first painted with a big brush, the small one does the rest. Saves '
                    'thousands of strokes on backgrounds and skies. 0 — off.',
                    '16 px suits most pictures.',
                    '16 px', 'Faster on backgrounds', 'ok'),
    'brushShape': _h('Brush shape', _BRUSH,
                     'A square brush lays pixels edge to edge — no gaps. A round one is softer, but leaves gaps between '
                     'neighbouring dots.',
                     'Almost always — square.',
                     'Square', 'Round = gaps', 'warn'),
    'lines': _h('Lines', _BRUSH,
                'How runs of one colour are painted. “Jump” presses at the start and jumps to the end: fast, but at low '
                'FPS the game may not finish the line. “Drag” moves the mouse in small steps. “Shift + line” uses the '
                'built-in straight line of the game.',
                'If lines on the picture are broken — switch to “Drag”.',
                'Jump to vertex', 'Affects reliability'),
    'fillFirst': _h('Fill the background first', _BRUSH,
                    'Before painting, fills the whole canvas with the most common colour of the picture using the fill '
                    'tool of the game. That colour then does not need to be painted pixel by pixel.',
                    'Turn it off if the sign already has something you want to keep.',
                    'on', 'Faster', 'ok'),
    'speed': _h('Speed', _SPEED,
                'Overall speed multiplier. Above 1.00× the program waits for the game less — faster, but some strokes may '
                'not land (red ones).',
                'Run the “Speed test” first and only then touch the multiplier.',
                '1.00×', 'Higher = risk of misses', 'warn'),
    'fps': _h('Game FPS', _SPEED,
              'The game accepts a mouse action only on the next frame. Knowing the FPS, the program waits exactly as long '
              'as needed. 0 — ignore, wait with a margin.',
              'Check the in-game FPS with the sign editor open and enter it here.',
              '60', 'More exact time estimate', 'ok'),
    'delay': _h('Action delay, ms', _SPEED,
                'Extra pause after every click or mouse move. Add some if the game “swallows” strokes even after the speed '
                'test.',
                'Raise it in steps of 5 ms.',
                '20 ms (if FPS is not set)', 'More = slower'),
    'colorPause': _h('Colour change pause, ms', _SPEED,
                     'How long to wait after entering a new colour until the game applies it to the brush. If the first '
                     'dots of a new colour come out in the old one — increase it.',
                     'With HEX input 40–80 ms is usually enough.',
                     '15 ms', 'Multiplied by the number of colour changes'),
    'saveEvery': _h('Save every N strokes', _SPEED,
                    'After how many strokes to press save in the game. By default it saves only at the end: the “Save '
                    'changes” button may close the editor in the middle of painting.',
                    '500 is reasonable: you lose at most ~30 seconds of work.',
                    'only at the end', 'Barely affects time', 'ok'),
    'verify': _h('Verification passes', _SPEED,
                 'After painting the program takes a screenshot, compares it with the plan and repaints missed pixels. '
                 'Each pass is one more screenshot and a short touch-up.',
                 '1 pass catches almost all misses. 0 — do not check.',
                 '2', '+5–10% time'),
    'countdown': _h('Countdown before start, s', _SPEED,
                    'How many seconds you get to switch to the game after pressing “Paint”. The countdown is shown in the '
                    'HUD, F8 cancels the start.',
                    '3–5 seconds is enough if the sign editor is already open.',
                    '3 s', 'Does not affect the picture', 'ok'),
}
