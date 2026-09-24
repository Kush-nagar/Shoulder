/**
 * Static drill library for players 13 to 18 (docs/design/player-redesign-brief.md,
 * section 8). Written by coaches, not generated. No API, no database.
 */

export const focuses = [
  "Scanning",
  "First touch",
  "Receiving on the half-turn",
  "Passing",
  "Ball mastery",
  "1v1",
  "Both feet",
  "Defending",
] as const;

export type Focus = (typeof focuses)[number];

export type Drill = {
  slug: string;
  title: string;
  focus: Focus;
  goalKeywords: string[];
  why: string;
  steps: string[];
  space: string;
  equipment: string;
  minutes: number;
  harder: string;
};

export const drills: Drill[] = [
  {
    slug: "two-look-receive",
    title: "Two-look receive",
    focus: "Scanning",
    goalKeywords: ["shoulder", "scan", "look", "check"],
    why: "Looking twice before the ball arrives tells you where the space is before you need it.",
    steps: [
      "A partner passes from 10 m.",
      "A second partner stands behind you and holds up 1 to 3 fingers.",
      "Look over your shoulder once as the pass is played and once just before it arrives.",
      "Call the number out loud, then take your touch away from the side your partner stands on.",
      "Swap roles every 8 passes.",
    ],
    space: "15 x 10 m",
    equipment: "1 ball, 2 cones",
    minutes: 12,
    harder: "Partner moves side to side after the pass.",
  },
  {
    slug: "gate-scan",
    title: "Gate scan",
    focus: "Scanning",
    goalKeywords: ["shoulder", "scan", "look"],
    why: "Builds the habit of checking which way is open before you receive.",
    steps: [
      "Set two cone gates 5 m behind you, left and right.",
      "A partner stands behind you and steps into one gate as the pass comes.",
      "Check your shoulder, then turn through the gate your partner is not in.",
      "Dribble through and pass back.",
      "Ten turns, rest, repeat.",
    ],
    space: "15 x 15 m",
    equipment: "1 ball, 6 cones",
    minutes: 10,
    harder: "Receive with your back fully to the gates.",
  },
  {
    slug: "wall-first-touch",
    title: "Wall first touch",
    focus: "First touch",
    goalKeywords: ["touch", "control", "receive"],
    why: "A clean first touch into space gives you time for the next action.",
    steps: [
      "Stand 5 m from a wall.",
      "Pass with your right foot, cushion with your left, pass again.",
      "Next set, take the touch across your body into a cone gate 1 m to the side.",
      "Swap feet.",
      "Step back to 8 m and use firmer passes.",
    ],
    space: "A wall and 8 m in front",
    equipment: "1 ball, 2 cones",
    minutes: 10,
    harder: "Receive on the half-volley.",
  },
  {
    slug: "open-body-angle",
    title: "Open body angle",
    focus: "Receiving on the half-turn",
    goalKeywords: ["half-turn", "turn", "body", "receive"],
    why: "Standing side-on lets you see more of the pitch and play forward in one touch.",
    steps: [
      "A partner passes from the side.",
      "Stand side-on, back foot pointing where you want to go.",
      "Receive on your back foot and play forward to a target cone gate.",
      "Change sides every 6 passes.",
      "Film one set side-on to check your angle.",
    ],
    space: "20 x 10 m",
    equipment: "1 ball, 4 cones",
    minutes: 12,
    harder: "Add a passive defender who steps in from behind.",
  },
  {
    slug: "half-turn-pressure",
    title: "Half-turn under pressure",
    focus: "Receiving on the half-turn",
    goalKeywords: ["half-turn", "turn", "pressure"],
    why: "Game passes arrive with a defender close; practising the half-turn with pressure makes it usable.",
    steps: [
      "Play in threes: server, you, defender behind you.",
      "Check your shoulder as the pass is played.",
      "If the defender is tight, set the ball back. If they are off, half-turn and dribble to the far line.",
      "Defender goes at half pace to start.",
      "Rotate after 6 balls.",
    ],
    space: "20 x 15 m",
    equipment: "1 ball, 4 cones, bib",
    minutes: 15,
    harder: "Defender at full pace.",
  },
  {
    slug: "triangle-look",
    title: "Triangle passing with a look",
    focus: "Passing",
    goalKeywords: ["pass", "scan", "tempo"],
    why: "Passing sharply while checking around you keeps the ball moving in games.",
    steps: [
      "Three players in a triangle 10 m apart.",
      "Pass and follow your pass to the next cone.",
      "Before each receive, glance away from the ball once.",
      "Two touches, then one touch.",
      "Change direction every 2 minutes.",
    ],
    space: "10 m triangle",
    equipment: "1 ball, 3 cones",
    minutes: 12,
    harder: "Add a second ball.",
  },
  {
    slug: "switch-the-play",
    title: "Switch the play",
    focus: "Passing",
    goalKeywords: ["switch", "long", "pass", "vision"],
    why: "A good switch moves the whole game and needs a look before the ball arrives.",
    steps: [
      "Two partners 25 m apart on opposite sides.",
      "Receive from one, open your body, and pass long to the other.",
      "Look to the target side before the first pass reaches you.",
      "Aim to land it in front of your partner, not at them.",
      "Rotate positions each set.",
    ],
    space: "30 x 20 m",
    equipment: "1 ball, 4 cones",
    minutes: 15,
    harder: "Two-touch maximum.",
  },
  {
    slug: "box-ball-mastery",
    title: "Box ball mastery",
    focus: "Ball mastery",
    goalKeywords: ["touch", "close control", "dribble"],
    why: "Many small touches build the close control you need in tight spaces.",
    steps: [
      "Mark a 3 m box.",
      "30 seconds each: sole rolls, inside-outside touches, pull-backs, drag-and-push.",
      "Keep your head up between touches and look at a cone outside the box.",
      "Rest 30 seconds between patterns.",
      "Two rounds.",
    ],
    space: "3 x 3 m",
    equipment: "1 ball, 4 cones",
    minutes: 10,
    harder: "A partner calls a colour and you touch that cone.",
  },
  {
    slug: "one-v-one-gate",
    title: "1v1 to a gate",
    focus: "1v1",
    goalKeywords: ["dribble", "beat", "1v1", "attack"],
    why: "Attacking a defender at speed and choosing a side is a skill you only build by doing it.",
    steps: [
      "Attacker and defender 15 m apart, two gates behind the defender.",
      "Defender passes to the attacker to start.",
      "Attacker drives at the defender and dribbles through either gate.",
      "Defender tries to win the ball or push the attacker wide.",
      "Swap roles after each go.",
    ],
    space: "20 x 15 m",
    equipment: "1 ball, 6 cones",
    minutes: 15,
    harder: "Attacker must check their shoulder before the first touch.",
  },
  {
    slug: "other-foot-wall",
    title: "Other-foot wall work",
    focus: "Both feet",
    goalKeywords: ["other foot", "left", "right", "both feet"],
    why: "Being able to use both feet means defenders can't show you one way.",
    steps: [
      "Stand 6 m from a wall.",
      "Use only the foot you use less: 20 inside-foot passes.",
      "Then 20 laces passes.",
      "Then receive with that foot and pass with it.",
      "Finish with 10 one-touch passes.",
    ],
    space: "A wall and 10 m",
    equipment: "1 ball",
    minutes: 12,
    harder: "Step back to 10 m.",
  },
  {
    slug: "jockey-show-wide",
    title: "Jockey and show wide",
    focus: "Defending",
    goalKeywords: ["defend", "press", "1v1", "tackle"],
    why: "Staying on your feet and guiding the attacker away from goal wins more balls than diving in.",
    steps: [
      "Channel 8 m wide and 20 m long.",
      "Attacker dribbles toward your end line.",
      "Get side-on, knees bent, and steer them toward one touchline.",
      "Only tackle when their touch goes too far.",
      "Swap after each go.",
    ],
    space: "20 x 8 m",
    equipment: "1 ball, 4 cones",
    minutes: 12,
    harder: "Attacker can pass to a partner at the end line.",
  },
  {
    slug: "talk-and-receive",
    title: "Talk and receive",
    focus: "Scanning",
    goalKeywords: ["communicate", "talk", "scan", "awareness"],
    why: "Calling “man on” or “time” helps teammates, and listening for it helps you choose your touch.",
    steps: [
      "Groups of three: passer, receiver, caller behind the receiver.",
      "Caller shouts “time” or “man on” as the pass is played.",
      "On “time”, turn and play forward. On “man on”, set it back first time.",
      "Receiver also checks their shoulder to confirm the call.",
      "Rotate every 8 passes.",
    ],
    space: "15 x 10 m",
    equipment: "1 ball, 2 cones",
    minutes: 12,
    harder: "Caller sometimes stays silent and the receiver decides alone.",
  },
];

export function drillBySlug(slug: string) {
  return drills.find((drill) => drill.slug === slug);
}

/** Drills whose keywords appear in the goal's title or description. */
export function drillsForGoal(
  goal: { title: string; description?: string | null } | null | undefined,
) {
  if (!goal) return [];
  const text = `${goal.title} ${goal.description ?? ""}`.toLowerCase();
  return drills.filter((drill) =>
    drill.goalKeywords.some((keyword) => text.includes(keyword)),
  );
}

/** One drill per day, stable for the whole day, from the goal's matches. */
export function drillOfTheDay(
  goal: { title: string; description?: string | null } | null | undefined,
  now = new Date(),
) {
  const pool = drillsForGoal(goal);
  const list = pool.length ? pool : drills;
  const start = Date.UTC(now.getUTCFullYear(), 0, 0);
  const day = Math.floor((now.getTime() - start) / 86_400_000);
  return list[day % list.length];
}

export function focusSlug(focus: Focus) {
  return focus.toLowerCase().replace(/\s+/g, "-");
}

export function focusFromSlug(slug: string | undefined) {
  return focuses.find((focus) => focusSlug(focus) === slug);
}
