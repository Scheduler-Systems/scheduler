export function renderScheduleShell(root, schedule) {
  root.innerHTML = `
    <section class="topbar">
      <div>
        <p class="label">${schedule.tenantId}</p>
        <h1 class="title">Scheduler</h1>
        <p>${schedule.name}</p>
      </div>
      <p class="label">${schedule.scheduleId}</p>
    </section>
    <section class="mode-grid" aria-label="Modes">
      <article class="panel">
        <p class="label">Manager mode</p>
        <strong>${schedule.managerMode.label}</strong>
      </article>
      <article class="panel">
        <p class="label">Worker mode</p>
        <strong>${schedule.workerMode.label}</strong>
      </article>
    </section>
    <section class="shift-grid" aria-label="Shifts">
      ${schedule.shifts.map((shift) => `
        <article class="panel">
          <p class="label">${shift.day}</p>
          <strong>${shift.startTime}-${shift.endTime}</strong>
          <p>${shift.assignedWorker}</p>
        </article>
      `).join("")}
    </section>
  `;
}
