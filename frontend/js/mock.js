/* Placeholder data shaped exactly like the backend's responses, so the UI can
   be built and demoed before the API is up. api.js falls back to these
   automatically when a request fails; nothing here is used once the backend
   answers. Keep the shapes in sync with backend/schemas.py. */

const iso = (minsAgo) => new Date(Date.now() - minsAgo * 60000).toISOString();

export const MOCK_USER = {
  id: "mock-user", name: "Maya Chen", email: "maya@example.com",
  username: "mayadoesgood", city: "Baltimore",
  tier: "Silver", tier_points: 184, points_to_next_tier: 316,
  current_streak: 13, longest_streak: 13,
  badges: [
    { code: "first_shift", label: "First Shift" },
    { code: "ten_day_streak", label: "10-Day Streak" },
  ],
};

export const MOCK_QUESTS = [
  { org_name: "Maryland Food Bank", address: "2200 Halethorpe Farms Rd", lat: 39.3359, lng: -76.6165,
    category: "food_bank", legitimacy_score: 0.85, quest_type: "daily",
    verified: true, estimated_points: 36, distance_km: 0.8 },
  { org_name: "Maryland SPCA", address: "3300 Falls Rd", lat: 39.3429, lng: -76.6275,
    category: "animal_shelter", legitimacy_score: 0.9, quest_type: "daily",
    verified: true, estimated_points: 31, distance_km: 1.4 },
  { org_name: "The Baltimore Station", address: "140 W West St", lat: 39.3209, lng: -76.6095,
    category: "homeless_shelter", legitimacy_score: 0.78, quest_type: "monthly",
    verified: true, estimated_points: 53, distance_km: 2.1 },
  { org_name: "Lennox Street Community Garden", address: "1400 Lennox St", lat: 39.3255, lng: -76.6310,
    category: "environmental", legitimacy_score: 0.83, quest_type: "daily",
    verified: false, estimated_points: 28, distance_km: 1.9 },
  { org_name: "Village Learning Place", address: "2521 St Paul St", lat: 39.3268, lng: -76.6161,
    category: "education", legitimacy_score: 0.7, quest_type: "monthly",
    verified: true, estimated_points: 44, distance_km: 1.1 },
  { org_name: "Soup for the Soul Dundalk", address: "7 Center Pl", lat: 39.3180, lng: -76.6240,
    category: "food_bank", legitimacy_score: 0.7, quest_type: "daily",
    verified: false, estimated_points: 33, distance_km: 2.6 },
];

export const MOCK_REPORTS = [
  { report_id: "r1", photo_url: "", description: "Trash along Temescal Creek footbridge",
    lat: 39.3320, lng: -76.6150, status: "open", claimed_by: null, created_at: iso(18),
    reported_by: "u-lena", reported_by_name: "Lena R.", claimed_by_name: null,
    estimated_points: 20, awaiting_confirmation: false, points_awarded: null },
  { report_id: "r2", photo_url: "", description: "Flyers covering the bus shelter at Broadway & 30th",
    lat: 39.3270, lng: -76.6090, status: "claimed", claimed_by: "u-jordan", created_at: iso(42),
    reported_by: "u-omar", reported_by_name: "Omar D.", claimed_by_name: "Jordan K.",
    estimated_points: 20, awaiting_confirmation: false, points_awarded: null },
  { report_id: "r3", photo_url: "", description: "Tree bed needs weeding at Lakeside Park",
    lat: 39.3355, lng: -76.6255, status: "open", claimed_by: null, created_at: iso(66),
    reported_by: "u-priya", reported_by_name: "Priya S.", claimed_by_name: null,
    estimated_points: 20, awaiting_confirmation: false, points_awarded: null },
];

export const MOCK_LEADERBOARD = [
  { rank: 1, user_id: "u-lena",   name: "Lena R.",   points: 288, deed_count: 8, is_you: false },
  { rank: 2, user_id: "u-theo",   name: "Theo M.",   points: 246, deed_count: 7, is_you: false },
  { rank: 3, user_id: "u-ana",    name: "Ana P.",    points: 211, deed_count: 6, is_you: false },
  { rank: 4, user_id: "mock-user", name: "Maya C.",  points: 184, deed_count: 5, is_you: true },
  { rank: 5, user_id: "u-jordan", name: "Jordan K.", points: 172, deed_count: 5, is_you: false },
  { rank: 6, user_id: "u-priya",  name: "Priya S.",  points: 161, deed_count: 4, is_you: false },
  { rank: 7, user_id: "u-omar",   name: "Omar D.",   points: 154, deed_count: 4, is_you: false },
];

export const MOCK_SCORE = {
  id: "mock-sub", user_id: "mock-user", org_name: "Maryland Food Bank",
  photo_url: "", description: "", time_spent_minutes: 90,
  lat: 39.3299, lng: -76.6205, submitted_at: new Date().toISOString(),
  points: 36, tier_points: 36, authenticity_confidence: 0.92,
  rationale: "The photo shows donation crates being sorted, which matches your description of the shift.",
  user_tier: "Silver", user_tier_points: 220, current_streak: 13, is_personal_best: true,
};
