/* Friends activity feed: what people you know have been doing.
 *
 * Reactions are optimistic -- the count moves the instant you tap, then
 * reconciles with the server's answer. A 300ms wait to see your own clap
 * appear makes the whole thing feel broken, and the failure case (revert,
 * toast) is rare and cheap.
 */

import { api, ApiError } from "../api.js";
import {
  confirmDelete, deedIcon, empty, esc, h, initials, prettyCategory, spinner,
  statusbar, tierBadge, timeAgo, toast,
} from "../ui.js";
import { go } from "../router.js";

const EMOJI = ["👏", "❤️", "🔥", "🙌", "💪"];

export async function renderFeed(root) {
  root.innerHTML = `
    ${statusbar()}
    <div class="hero">
      <div>
        <div class="eyebrow">Your people</div>
        <h2>Activity</h2>
        <p class="muted" style="margin-top:4px">What your team has been up to.</p>
      </div>
      <button class="btn btn-ghost btn-sm" id="to-ranks">Ranks</button>
    </div>
    <div class="pad" id="feed-list" style="padding-top:0">${spinner()}</div>`;

  root.querySelector("#to-ranks").onclick = () => go("leaderboard");

  const list = root.querySelector("#feed-list");

  const load = async () => {
    const items = await api.feed();
    if (!items.length) {
      list.innerHTML = empty(
        "🌤️", "Nothing here yet",
        "Log a deed, or share your team code from your profile so friends show up here.",
      );
      return;
    }
    list.replaceChildren(...items.map(feedCard));
  };

  await load();
}

export function feedCard(item) {
  const card = h(`
    <div class="card feed-item">
      <div class="row" style="align-items:flex-start">
        <span class="avatar">${item.user_avatar
          ? `<img src="${esc(item.user_avatar)}" alt="" style="width:100%;height:100%;object-fit:cover">`
          : esc(initials(item.user_name))}</span>
        <div class="grow">
          <div class="meta-row">
            <strong style="font-size:14.5px">${esc(item.user_name)}</strong>
            ${tierBadge(item.user_tier)}
            ${item.verified_presence ? `<span class="verified">✓ verified</span>` : ""}
          </div>
          <p class="tiny" style="margin-top:2px">
            ${deedIcon(item.deed_type)} ${esc(prettyCategory(item.deed_type))}
            ${item.org_name ? "· " + esc(item.org_name) : ""} · ${timeAgo(item.created_at)}
          </p>
        </div>
        <span class="row" style="gap:6px">
          <span class="chip chip-quiet">+${item.points}</span>
          ${item.is_mine ? `<button class="delete-btn" data-del-deed>Delete</button>` : ""}
        </span>
      </div>

      ${item.description
        ? `<p class="feed-desc">${esc(item.description)}</p>` : ""}

      <div class="reaction-row" data-reactions></div>

      <div class="feed-comments" data-comments></div>

      <form class="comment-form" data-comment-form>
        <input type="text" placeholder="Say something nice…" maxlength="280" aria-label="Add a comment">
        <button type="submit" class="btn btn-primary btn-sm">Post</button>
      </form>
    </div>`);

  const delDeed = card.querySelector("[data-del-deed]");
  if (delDeed) {
    delDeed.onclick = async () => {
      const yes = await confirmDelete({
        title: "Delete this deed?",
        body: `The ${item.points} points it earned will be taken back.`,
      });
      if (!yes) return;
      try {
        await api.deleteSubmission(item.submission_id);
        card.remove();
        toast("Deed deleted");
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "Couldn't delete that", true);
      }
    };
  }

  paintReactions(card, item);
  paintComments(card, item);

  card.querySelector("[data-comment-form]").onsubmit = async (e) => {
    e.preventDefault();
    const input = e.target.querySelector("input");
    const text = input.value.trim();
    if (!text) return;
    input.disabled = true;
    try {
      const updated = await api.comment(item.submission_id, text);
      input.value = "";
      Object.assign(item, updated);
      paintComments(card, updated);
      paintReactions(card, updated);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't post that", true);
    } finally {
      input.disabled = false;
      input.focus();
    }
  };

  return card;
}

function paintReactions(card, item) {
  const row = card.querySelector("[data-reactions]");
  row.replaceChildren(
    ...EMOJI.map((emoji) => {
      const found = item.reactions.find((r) => r.emoji === emoji);
      const count = found?.count ?? 0;
      const mine = found?.mine ?? false;
      const btn = h(`
        <button class="react-btn ${mine ? "mine" : ""}" aria-pressed="${mine}"
                aria-label="React ${emoji}">
          <span>${emoji}</span>${count ? `<em>${count}</em>` : ""}
        </button>`);

      btn.onclick = async () => {
        // Optimistic: move the count now, reconcile after. Waiting on a
        // round trip to see your own tap land feels broken.
        const before = JSON.parse(JSON.stringify(item.reactions));
        const existing = item.reactions.find((r) => r.emoji === emoji);
        if (existing?.mine) {
          existing.count -= 1;
          existing.mine = false;
          if (existing.count <= 0) item.reactions = item.reactions.filter((r) => r.emoji !== emoji);
        } else if (existing) {
          existing.count += 1;
          existing.mine = true;
        } else {
          item.reactions.push({ emoji, count: 1, mine: true });
        }
        paintReactions(card, item);

        try {
          const updated = await api.react(item.submission_id, emoji);
          Object.assign(item, updated);
          paintReactions(card, updated);
        } catch (err) {
          item.reactions = before;
          paintReactions(card, item);
          toast(err instanceof ApiError ? err.message : "Couldn't react", true);
        }
      };
      return btn;
    }),
  );
}

function paintComments(card, item) {
  const box = card.querySelector("[data-comments]");
  if (!item.comments.length) {
    box.replaceChildren();
    return;
  }
  const hidden = item.comment_count - item.comments.length;
  box.replaceChildren(
    ...(hidden > 0
      ? [h(`<p class="tiny" style="margin-bottom:6px">${hidden} earlier comment${hidden === 1 ? "" : "s"}</p>`)]
      : []),
    ...item.comments.map((c) => {
      const row = h(`
        <p class="feed-comment">
          <strong>${esc(c.user_name)}</strong> ${esc(c.text)}
          ${c.is_mine || item.is_mine ? `<button class="delete-btn" data-del-c>×</button>` : ""}
        </p>`);
      const del = row.querySelector("[data-del-c]");
      if (del) {
        del.onclick = async () => {
          try {
            await api.deleteComment(c.id);
            row.remove();
          } catch (err) {
            toast(err instanceof ApiError ? err.message : "Couldn't delete that", true);
          }
        };
      }
      return row;
    }),
  );
}
