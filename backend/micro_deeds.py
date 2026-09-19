"""Everyday good deeds: small, specific, and done in a minute.

Most of the app is built around effort you can evidence -- a shift, a
receipt, a cleanup photo. This is the other half of doing good: holding a
door, picking up three bits of litter, telling someone they did a good job.
None of that produces evidence, and demanding a photo would both kill the
spontaneity and make people stage things that already happened.

So these run on the honour system, and the design leans on that rather than
fighting it:

* Points are small (2-5) and the daily total is capped, so tapping every
  task every day earns less than one real shift. There is nothing worth
  farming.
* Each task can be completed once per day, so the list is a prompt to go do
  something, not a button to mash.
* No AI call, no upload, no network wait. Tap, done. The moment a quick
  kindness needs a five-second vision check, it stops being quick.

Tasks are phrased as specific actions, not virtues. "Be kind today" is
unactionable; "let one person go ahead of you in a queue" is something you
can finish before lunch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class MicroDeed:
    id: str
    text: str
    icon: str
    points: int
    theme: str  # people | place | connection | civic


MICRO_DEEDS: tuple[MicroDeed, ...] = (
    # --- Kindness to people ---------------------------------------------
    MicroDeed("compliment", "Give someone a genuine compliment — something specific, not just 'nice shirt'", "💬", 3, "people"),
    MicroDeed("hold_door", "Hold a door for someone behind you", "🚪", 2, "people"),
    MicroDeed("let_ahead", "Let one person go ahead of you in a queue", "🙂", 2, "people"),
    MicroDeed("give_seat", "Give up your seat to someone who needs it more", "💺", 3, "people"),
    MicroDeed("thank_by_name", "Thank someone who served you today, and use their name", "🙏", 3, "people"),
    MicroDeed("help_carry", "Offer to help someone carry something heavy", "💪", 3, "people"),
    MicroDeed("directions", "Help someone who looks lost", "🧭", 3, "people"),
    MicroDeed("take_photo", "Offer to take a photo for a group so nobody gets left out", "📷", 2, "people"),
    MicroDeed("bigger_tip", "Leave a bigger tip than you normally would", "💸", 3, "people"),
    MicroDeed("pram_stairs", "Help someone with a pram, case or trolley up the stairs", "🧳", 4, "people"),
    MicroDeed("patient_parent", "Tell a parent having a hard time with their kid that they're doing fine", "👶", 4, "people"),
    MicroDeed("charger", "Lend a stranger your charger or a bit of battery", "🔌", 2, "people"),

    # --- Looking after the place ----------------------------------------
    MicroDeed("three_pieces", "Pick up three pieces of litter that aren't yours", "🧹", 4, "place"),
    MicroDeed("bin_it", "Bin something you found on the pavement on your way past", "🗑️", 2, "place"),
    MicroDeed("clear_drain", "Clear leaves or rubbish from a blocked drain", "🍂", 4, "place"),
    MicroDeed("recycle_right", "Properly recycle something you'd normally throw away", "♻️", 2, "place"),
    MicroDeed("return_trolley", "Return a stray shopping trolley to the bay", "🛒", 2, "place"),
    MicroDeed("neighbour_bins", "Bring in a neighbour's bins", "🏠", 3, "place"),
    MicroDeed("water_plant", "Water a neighbour's or a public plant", "🌱", 2, "place"),
    MicroDeed("report_broken", "Report a broken streetlight, pothole or fly-tipping to the council", "🔧", 4, "civic"),
    MicroDeed("dog_water", "Top up a public water bowl for dogs", "🐕", 2, "place"),
    MicroDeed("move_creature", "Move a snail, worm or beetle off the pavement", "🐌", 2, "place"),

    # --- Staying connected ----------------------------------------------
    MicroDeed("check_in", "Check in on someone who lives alone", "☎️", 5, "connection"),
    MicroDeed("old_friend", "Message someone you haven't spoken to in months", "💌", 3, "connection"),
    MicroDeed("thank_you_note", "Write a thank-you note to a teacher, nurse, driver or carer", "✍️", 4, "connection"),
    MicroDeed("learn_name", "Learn the name of someone you see regularly but have never asked", "👋", 3, "connection"),
    MicroDeed("greet_three", "Say hello to three people you'd normally walk past", "😀", 2, "connection"),
    MicroDeed("listen", "Ask someone how they're doing, and actually wait for the answer", "👂", 3, "connection"),
    MicroDeed("share_lost_pet", "Share a neighbour's lost-pet or community post", "📣", 2, "connection"),
    MicroDeed("praise_publicly", "Tell someone's manager they did a good job", "⭐", 4, "connection"),

    # --- Small giving ----------------------------------------------------
    MicroDeed("give_book", "Give away a book you've finished", "📚", 3, "place"),
    MicroDeed("declutter_one", "Set aside one thing you don't use for the charity shop", "👕", 3, "place"),
    MicroDeed("buy_extra", "Buy one extra item for the food bank box on your shop", "🥫", 5, "place"),
    MicroDeed("snack_driver", "Leave a drink or snack out for a delivery driver", "🥤", 3, "people"),
    MicroDeed("parking_meter", "Feed an expiring parking meter that isn't yours", "🅿️", 3, "people"),

    # --- Civic -----------------------------------------------------------
    MicroDeed("local_review", "Leave an honest positive review for a small local business", "🏪", 3, "civic"),
    MicroDeed("read_local", "Read one thing about a local issue you'd usually scroll past", "📰", 2, "civic"),
    MicroDeed("register_vote", "Check your voter registration is current", "🗳️", 4, "civic"),
    MicroDeed("organ_donor", "Check whether you're on the organ donor register", "❤️", 5, "civic"),
    MicroDeed("let_merge", "Let a car merge in front of you", "🚗", 2, "civic"),
)

BY_ID = {d.id: d for d in MICRO_DEEDS}

#: How many suggestions to show each day. Enough to pick from, few enough
#: that the list reads as a prompt rather than a chore list.
DAILY_COUNT = 6

#: Ceiling on points from tap-to-complete deeds per day. A full day of these
#: is worth less than one verified shift, which is the point -- they widen
#: what counts as doing good without becoming the efficient way to climb.
DAILY_POINT_CAP = 20


def deeds_for_day(day: date | None = None) -> list[MicroDeed]:
    """The day's suggestions: same for everyone, rotating with the date.

    Strided rather than sliced so a day's six span different themes instead
    of being six consecutive litter tasks.
    """
    day = day or date.today()
    offset = day.toordinal() % len(MICRO_DEEDS)
    stride = 7  # coprime with 40, so it walks the whole list before repeating
    return [MICRO_DEEDS[(offset + i * stride) % len(MICRO_DEEDS)] for i in range(DAILY_COUNT)]
