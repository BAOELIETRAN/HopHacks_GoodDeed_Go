/* What a community post paid, in words. Pure functions, no DOM and no imports,
   so they can be tested in plain Node.

   Both people are credited when the poster confirms a task: the helper(s) who
   did the work, and the poster who reported it. Which number a card shows
   depends on who is looking. */

/** The points figure on a community card, from the viewer's point of view. */
export function creditLabel(report) {
  if (report.status !== "done") return `+${report.estimated_points ?? 20} pts`;
  if (report.claimed_by_me && report.points_awarded) return `+${report.points_awarded} pts earned`;
  if (report.is_mine && report.reporter_points_awarded) {
    return `+${report.reporter_points_awarded} pts for reporting`;
  }
  if (report.points_awarded) return `+${report.points_awarded} pts awarded`;
  // Confirmed before payouts were recorded on the post: say it is done rather
  // than claim nobody was paid.
  return "completed";
}

/** The toast shown to the poster right after they confirm. */
export function completionMessage(done) {
  const helpers = (done.filled_slots || 0) > 1;
  const helperPart = helpers
    ? `helpers earned +${done.points_awarded} each`
    : `the helper earned +${done.points_awarded}`;
  return `Confirmed. You earned +${done.reporter_points_awarded} pts, and ${helperPart}.`;
}
