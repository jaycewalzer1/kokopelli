// Keeps the run's log. Polling only adds to it; the app decides how fast events get applied.
const POLL_MS = 300;

export class Feed {
  constructor(run, onError) {
    this.run = run;
    this.log = [];
    this.status = null;
    this.stopped = false;
    this.onError = onError;
    this.poll();
  }

  async poll() {
    let full = false;
    try {
      const after = this.log.at(-1)?.seq ?? 0;
      const [events, status] = await Promise.all([
        fetch(`/api/feed?run=${this.run}&after=${after}`).then(response => response.json()),
        fetch(`/api/status?run=${this.run}`).then(response => response.json()),
      ]);
      if (this.stopped) return;
      this.log.push(...events);
      this.status = status;
      full = events.length >= 2000;
    } catch (error) {
      this.onError(error.message);
    }
    if (!this.stopped) setTimeout(() => this.poll(), full ? 0 : POLL_MS);
  }

  close() { this.stopped = true; }
}
