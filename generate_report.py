"""
Generate the ACM Technical Report as a PDF using reportlab.
Run: python generate_report.py
Output: ACM_Technical_Report.pdf
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, ListFlowable, ListItem
)
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT

doc = SimpleDocTemplate(
    "ACM_Technical_Report.pdf",
    pagesize=A4,
    topMargin=2*cm, bottomMargin=2*cm,
    leftMargin=2.5*cm, rightMargin=2.5*cm,
)

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(
    'Title2', parent=styles['Title'], fontSize=22, spaceAfter=6,
    textColor=HexColor('#1a1a2e'),
))
styles.add(ParagraphStyle(
    'Subtitle', parent=styles['Normal'], fontSize=12,
    alignment=TA_CENTER, spaceAfter=20,
    textColor=HexColor('#555555'),
))
styles.add(ParagraphStyle(
    'SectionHead', parent=styles['Heading1'], fontSize=14,
    spaceBefore=16, spaceAfter=8,
    textColor=HexColor('#1a1a2e'),
))
styles.add(ParagraphStyle(
    'SubHead', parent=styles['Heading2'], fontSize=11,
    spaceBefore=10, spaceAfter=4,
    textColor=HexColor('#2d2d44'),
))
styles.add(ParagraphStyle(
    'Body', parent=styles['Normal'], fontSize=10,
    leading=14, alignment=TA_JUSTIFY, spaceAfter=6,
))
styles.add(ParagraphStyle(
    'MonoCode', parent=styles['Normal'], fontSize=8,
    fontName='Courier', leading=10, spaceAfter=4,
    leftIndent=12,
))
styles.add(ParagraphStyle(
    'Caption', parent=styles['Normal'], fontSize=9,
    alignment=TA_CENTER, spaceAfter=10,
    textColor=HexColor('#666666'),
))

story = []
S = lambda tag, txt: story.append(Paragraph(txt, styles[tag]))
sp = lambda n=6: story.append(Spacer(1, n))

# ── Title Page ──
sp(60)
S('Title2', 'ACM: Autonomous Constellation Manager')
S('Subtitle', 'National Space Hackathon 2026 — Technical Report')
sp(10)
S('Subtitle', 'Team: SarmaHighOnCode')
S('Subtitle', 'Stack: Python 3.11 (FastAPI) + React (Vite) + Docker')
sp(20)
S('Body', '<b>Abstract.</b> This report details the architecture, numerical methods, and spatial '
  'optimization algorithms used in our Autonomous Constellation Manager (ACM). The system '
  'manages 50+ LEO satellites navigating 10,000+ tracked debris objects, providing autonomous '
  'collision avoidance, fuel-optimal evasion planning, and real-time operational visualization. '
  'Key innovations include a 4-stage KDTree conjunction pipeline achieving O(S log D) complexity, '
  'vectorized DOP853 batch propagation, and RTN-frame minimum-energy maneuver planning with '
  'dynamic recovery timing.')
story.append(PageBreak())

# ── Section 1: Architecture ──
S('SectionHead', '1. System Architecture')
S('Body', 'The ACM follows a modular, layered architecture with strict separation between '
  'the physics engine, API layer, and visualization frontend.')

S('SubHead', '1.1 Backend (Python 3.11 / FastAPI)')
S('Body', 'The backend is organized into six engine modules, each responsible for a single '
  'domain concern:')
items = [
    '<b>propagator.py</b> — DOP853 J2-perturbed orbital propagator with vectorized batch mode',
    '<b>collision.py</b> — 4-stage KDTree conjunction assessment pipeline',
    '<b>fuel_tracker.py</b> — Tsiolkovsky mass depletion with per-satellite state',
    '<b>maneuver_planner.py</b> — RTN-to-ECI evasion/recovery burn calculator',
    '<b>ground_stations.py</b> — Line-of-sight elevation check for 6 ground stations',
    '<b>simulation.py</b> — Master orchestrator coordinating all modules per tick',
]
story.append(ListFlowable(
    [ListItem(Paragraph(i, styles['Body'])) for i in items],
    bulletType='bullet', bulletFontSize=8, leftIndent=20,
))
sp()
S('Body', 'A single <b>config.py</b> serves as the source of truth for all physical constants '
  '(mu, J2, R_E, Isp, g0, dry mass, fuel mass, cooldown, signal delay, thresholds).')

S('SubHead', '1.2 Frontend (React + Vite + Canvas)')
S('Body', 'The frontend uses Zustand for state management and polls <b>GET /api/visualization/snapshot</b> '
  'every 2 seconds with exponential backoff retry. All heavy rendering (debris cloud, satellite '
  'trails, ground stations) uses the HTML5 Canvas API for 60fps performance at 10K+ objects.')

S('SubHead', '1.3 Deployment (Docker)')
S('Body', 'A single Dockerfile based on <b>ubuntu:22.04</b> builds both frontend (npm run build → '
  'static files) and backend, exposing port 8000. Auto-seeding on startup generates 50 satellites '
  '+ 10K debris + threat scenarios so the dashboard is immediately populated.')

# ── Section 2: Numerical Methods ──
S('SectionHead', '2. Numerical Methods')

S('SubHead', '2.1 Orbital Propagation: J2-Perturbed DOP853')
S('Body', 'We use scipy.integrate.solve_ivp with the DOP853 (8th-order Dormand-Prince) method '
  'to integrate the equations of motion. The acceleration model includes two-body gravity plus '
  'the J2 zonal harmonic perturbation:')
S('Code', 'a_total = -(mu / |r|^3) * r + a_J2')
S('Code', 'a_J2 = (3/2) * J2 * mu * R_E^2 / |r|^5 * [x(5z^2/r^2 - 1), y(5z^2/r^2 - 1), z(5z^2/r^2 - 3)]')
sp()
S('Body', '<b>Vectorized batch propagation:</b> All N objects are packed into a single 6N-element '
  'state vector and integrated in one ODE call. The derivatives function uses NumPy broadcasting '
  'to compute all N accelerations simultaneously, achieving O(1) solver overhead regardless of N. '
  'For a 15,000-object batch, this completes in under 30 seconds.')

S('SubHead', '2.2 Dense Output for Collision Refinement')
S('Body', 'We enable <b>dense_output=True</b> in solve_ivp to obtain a continuous polynomial '
  'representation of the trajectory. This allows evaluating positions at arbitrary sub-step times '
  'without re-integrating, critical for TCA refinement via Brent\'s method.')

S('SubHead', '2.3 Tsiolkovsky Rocket Equation')
S('Body', 'Fuel mass depletion follows the exact Tsiolkovsky formula:')
S('Code', 'delta_m = m_current * (1 - exp(-|dv| / (Isp * g0)))')
S('Body', 'where Isp = 300s, g0 = 9.80665 m/s^2. As fuel depletes, the satellite becomes lighter, '
  'making subsequent burns more efficient. The tracker dynamically updates wet mass after each burn.')

# ── Section 3: Spatial Optimization ──
S('SectionHead', '3. Spatial Optimization: 4-Stage Conjunction Pipeline')
S('Body', 'Checking every satellite against every debris object is O(S x D) = O(N^2), which is '
  'computationally infeasible for 50 satellites x 10,000 debris. Our 4-stage pipeline reduces '
  'this to O(D + S log D):')

table_data = [
    ['Stage', 'Algorithm', 'Complexity', 'Purpose'],
    ['1. Altitude Filter', 'Apo/Periapsis band', 'O(D)', 'Eliminate ~85% of debris by orbital altitude mismatch'],
    ['2. KDTree Query', 'scipy.spatial.KDTree', 'O(D_alt log D_alt)', 'Build spatial index of filtered debris; query at 200km radius'],
    ['3. TCA Refinement', 'Brent\'s method on DOP853 dense output', 'O(k * F)', 'Precise closest-approach time for k candidate pairs'],
    ['4. CDM Emission', 'Risk classification + logging', 'O(k)', 'Emit CDMs with CRITICAL/RED/YELLOW/GREEN risk levels'],
]
t = Table(table_data, colWidths=[65, 120, 80, 180])
t.setStyle(TableStyle([
    ('BACKGROUND', (0, 0), (-1, 0), HexColor('#1a1a2e')),
    ('TEXTCOLOR', (0, 0), (-1, 0), HexColor('#ffffff')),
    ('FONTSIZE', (0, 0), (-1, -1), 8),
    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
    ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#cccccc')),
    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ('TOPPADDING', (0, 0), (-1, -1), 4),
    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
]))
story.append(t)
sp(10)
S('Body', 'Stage 1 eliminates debris whose orbital altitude band does not overlap with any '
  'satellite\'s altitude +/- 50km. This typically removes 85% of debris before any spatial '
  'indexing occurs. The remaining debris enters Stage 2 (KDTree), reducing the effective D '
  'to ~1,500 objects.')

# ── Section 4: Maneuver Planning ──
S('SectionHead', '4. Maneuver Planning: RTN-Frame Optimization')

S('SubHead', '4.1 Minimum-Energy Evasion')
S('Body', 'When a CRITICAL CDM (miss &lt; 100m) is detected, the planner computes the minimum '
  'delta-v to achieve a 200m miss distance (2x safety margin). Using linear phasing theory:')
S('Code', 'dv_transverse = target_miss / (6 * lead_time)  [km/s]')
S('Body', 'The planner searches 36 candidate burn times in [TCA-3h, TCA-10min] at 5-minute '
  'intervals, selecting the time that minimizes delta-v while having ground station LOS. '
  'Burns are applied in the Transverse (T) direction of the RTN frame, which is the most '
  'fuel-efficient method for in-plane orbit phasing.')

S('SubHead', '4.2 RTN-to-ECI Transformation')
S('Body', 'The RTN basis vectors are computed from the satellite\'s position and velocity at '
  'the planned burn time (not current time — critical fix for rotating constellations):')
S('Code', 'R_hat = r / |r|              (Radial)')
S('Code', 'N_hat = (r x v) / |r x v|    (Normal)')
S('Code', 'T_hat = N_hat x R_hat         (Transverse)')
S('Code', 'dv_ECI = [R_hat | T_hat | N_hat] @ dv_RTN')

S('SubHead', '4.3 Dynamic Recovery Timing')
S('Body', 'Instead of a fixed 45-minute delay, the planner propagates both objects past TCA '
  'and triggers recovery when separation exceeds 50km (typically TCA+5-10min). This dramatically '
  'reduces out-of-slot time and improves uptime scores.')

S('SubHead', '4.4 Constraint Enforcement')
items2 = [
    '<b>Max delta-v:</b> 15 m/s per burn. Larger maneuvers are split into multi-burn sequences separated by 600s cooldowns.',
    '<b>Thruster cooldown:</b> 600s mandatory rest between any two burns on the same satellite.',
    '<b>Signal delay:</b> 10s minimum lead time for burn scheduling.',
    '<b>Ground station LOS:</b> Elevation angle check against 6 stations with per-station min elevation masks.',
    '<b>EOL protection:</b> Burns rejected for satellites with fuel &lt; 2.5 kg (5% threshold). Automatic graveyard orbit maneuver queued.',
]
story.append(ListFlowable(
    [ListItem(Paragraph(i, styles['Body'])) for i in items2],
    bulletType='bullet', bulletFontSize=8, leftIndent=20,
))

S('SubHead', '4.5 Fleet-Level Optimization')
S('Body', 'For satellite-vs-satellite conjunctions, a health-aware handshake ensures only the '
  'fuel-richer satellite (by &gt;2kg margin) performs the evasion. This prevents both satellites '
  'from burning simultaneously and conserves total fleet fuel budget.')

# ── Section 5: Frontend ──
S('SectionHead', '5. Frontend: Orbital Insight Dashboard')
S('Body', 'The dashboard provides five visualization modules rendered via HTML5 Canvas:')

items3 = [
    '<b>Ground Track Map</b> (Mercator): Real-time satellite positions, 90-min historical trails, '
    '90-min predicted trajectories, terminator line overlay, 10K+ debris as 1px Canvas dots.',
    '<b>Bullseye Plot</b> (Polar): Selected satellite at center, debris radial distance = TCA, '
    'angle = approach vector, color-coded by risk (GREEN/YELLOW/RED/CRITICAL with pulsing animation).',
    '<b>Fuel Heatmap</b>: Per-satellite fuel gauges sorted by remaining propellant, fleet status counters.',
    '<b>Delta-V Chart</b>: Fuel consumed vs. collisions avoided — demonstrates evasion algorithm efficiency.',
    '<b>Maneuver Timeline</b> (Gantt): Chronological burn blocks with 600s cooldown zones, CDM diamond markers, '
    'blackout overlap flagging, and current simulation time marker.',
]
story.append(ListFlowable(
    [ListItem(Paragraph(i, styles['Body'])) for i in items3],
    bulletType='bullet', bulletFontSize=8, leftIndent=20,
))

# ── Section 6: Performance ──
S('SectionHead', '6. Performance Benchmarks')
perf_data = [
    ['Benchmark', 'Result', 'Requirement'],
    ['100K debris ingest', '~2s', '<5s'],
    ['KDTree build (100K objects)', '<100ms', 'Real-time'],
    ['50 sat x 100K debris Stage-1 filter', '0.09s', '<1s'],
    ['15K vectorized batch propagation', '<30s', '<30s'],
    ['24h soak (86400s step)', '<30s', '<60s'],
    ['Snapshot API response (10K debris)', '<1s', '<3s'],
    ['Frontend FPS (10K debris)', '60fps', '60fps'],
]
t2 = Table(perf_data, colWidths=[180, 80, 80])
t2.setStyle(TableStyle([
    ('BACKGROUND', (0, 0), (-1, 0), HexColor('#1a1a2e')),
    ('TEXTCOLOR', (0, 0), (-1, 0), HexColor('#ffffff')),
    ('FONTSIZE', (0, 0), (-1, -1), 9),
    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
    ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#cccccc')),
    ('TOPPADDING', (0, 0), (-1, -1), 4),
    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
]))
story.append(t2)

# ── Section 7: Testing ──
S('SectionHead', '7. Test Coverage')
S('Body', 'The system includes three test suites totaling 100+ test cases:')
items4 = [
    '<b>test_physics_engine.py</b> (53KB, Sections 1-8): Unit tests for every engine module.',
    '<b>test_live_flood.py</b> (51 tests): 3-pillar stress suite — telemetry flood (100K objects), '
    'ground station LOS validation, physics benchmarks (Tsiolkovsky, RAAN drift, energy conservation).',
    '<b>test_grader_stress.py</b> (30 tests): Full grader scenario coverage — schema validation, '
    'bulk ingest, collision avoidance, constraint enforcement, blackout handling, fuel starvation, '
    'station-keeping, 24h soak, fragmentation cascade, edge cases.',
]
story.append(ListFlowable(
    [ListItem(Paragraph(i, styles['Body'])) for i in items4],
    bulletType='bullet', bulletFontSize=8, leftIndent=20,
))

doc.build(story)
print("Generated: ACM_Technical_Report.pdf")
