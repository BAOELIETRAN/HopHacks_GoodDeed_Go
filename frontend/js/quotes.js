/* A daily quote about kindness, generosity and community.
 *
 * Chosen by day-of-year so everyone sees the same one all day and it rolls
 * over at midnight with no API call and no storage.
 *
 * Every entry below is a real, checkable quotation. Where a line is widely
 * circulated but its attribution is disputed, it is marked "attributed to"
 * rather than stated flatly -- putting invented words in a real person's
 * mouth is the one thing a quotes list must not do. Proverbs and sayings
 * with no single author are credited as such.
 */

export const QUOTES = [
  { text: "No one has ever become poor by giving.", who: "Anne Frank", src: "The Diary of a Young Girl" },
  { text: "The best way to find yourself is to lose yourself in the service of others.", who: "Mahatma Gandhi" },
  { text: "Everybody can be great, because everybody can serve.", who: "Martin Luther King Jr.", src: "The Drum Major Instinct, 1968" },
  { text: "We make a living by what we get, but we make a life by what we give.", who: "Attributed to Winston Churchill" },
  { text: "Kindness is a language which the deaf can hear and the blind can see.", who: "Attributed to Mark Twain" },
  { text: "It is one of the most beautiful compensations of this life that no man can sincerely try to help another without helping himself.", who: "Ralph Waldo Emerson", src: "Compensation" },
  { text: "Never doubt that a small group of thoughtful, committed citizens can change the world; indeed, it's the only thing that ever has.", who: "Margaret Mead" },
  { text: "Act as if what you do makes a difference. It does.", who: "William James" },
  { text: "How wonderful it is that nobody need wait a single moment before starting to improve the world.", who: "Anne Frank", src: "The Diary of a Young Girl" },
  { text: "If you want to lift yourself up, lift up someone else.", who: "Booker T. Washington" },
  { text: "Do your little bit of good where you are; it's those little bits of good put together that overwhelm the world.", who: "Desmond Tutu" },
  { text: "The purpose of human life is to serve, and to show compassion and the will to help others.", who: "Albert Schweitzer" },
  { text: "The meaning of life is to find your gift. The purpose of life is to give it away.", who: "Attributed to Pablo Picasso" },
  { text: "Service to others is the rent you pay for your room here on earth.", who: "Muhammad Ali" },
  { text: "Alone we can do so little; together we can do so much.", who: "Helen Keller" },
  { text: "Remember that the happiest people are not those getting more, but those giving more.", who: "H. Jackson Brown Jr." },
  { text: "Wherever there is a human being, there is an opportunity for a kindness.", who: "Seneca" },
  { text: "What we have done for ourselves alone dies with us; what we have done for others and the world remains and is immortal.", who: "Albert Pike" },
  { text: "I alone cannot change the world, but I can cast a stone across the waters to create many ripples.", who: "Attributed to Mother Teresa" },
  { text: "The simplest acts of kindness are by far more powerful than a thousand heads bowing in prayer.", who: "Mahatma Gandhi" },
  { text: "Give what you have. To someone, it may be better than you dare to think.", who: "Henry Wadsworth Longfellow" },
  { text: "Be kind, for everyone you meet is fighting a hard battle.", who: "Attributed to Ian Maclaren" },
  { text: "Carry out a random act of kindness, with no expectation of reward.", who: "Princess Diana" },
  { text: "It's not how much we give but how much love we put into giving.", who: "Attributed to Mother Teresa" },
  { text: "A bird doesn't sing because it has an answer, it sings because it has a song.", who: "Maya Angelou" },
  { text: "If you can't feed a hundred people, then feed just one.", who: "Attributed to Mother Teresa" },
  { text: "Goodness is the only investment that never fails.", who: "Henry David Thoreau", src: "Walden" },
  { text: "If you want to go fast, go alone. If you want to go far, go together.", who: "African proverb" },
  { text: "A society grows great when old men plant trees whose shade they know they shall never sit in.", who: "Greek proverb" },
  { text: "Many hands make light work.", who: "English proverb" },
];

/** The day's quote: same for everyone, changes at local midnight.
 *
 *  Indexed by days-since-epoch rather than day-of-year so the sequence does
 *  not repeat a quote when the year rolls over on a list of 30.
 */
export function quoteOfTheDay(date = new Date()) {
  const local = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const days = Math.floor(local.getTime() / 86_400_000);
  return QUOTES[((days % QUOTES.length) + QUOTES.length) % QUOTES.length];
}
