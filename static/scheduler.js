export const ROLES = Object.freeze(["A", "B", "C"]);
export const DAY_TYPES = Object.freeze(["NORMAL", "BIG", "OFF", "CUSTOM"]);

export class ScheduleError extends Error {
  constructor(message) {
    super(message);
    this.name = "ScheduleError";
  }
}

function roundTo(value, digits) {
  return Number(value.toFixed(digits));
}

function makeRandom(seed) {
  let value = Number(seed) >>> 0;
  return () => {
    value = (value + 0x6d2b79f5) >>> 0;
    let mixed = value;
    mixed = Math.imul(mixed ^ (mixed >>> 15), mixed | 1);
    mixed ^= mixed + Math.imul(mixed ^ (mixed >>> 7), mixed | 61);
    return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296;
  };
}

function allowedRoles(name, config) {
  const configured = config.restrictedRoles?.[name];
  if (!configured) return [...ROLES];
  return configured.filter((role) => ROLES.includes(role));
}

function requirementsForDay(day, availableCount) {
  const dayType = String(day.day_type || "NORMAL").toUpperCase();
  if (dayType === "OFF") return { A: 0, B: 0, C: 0 };

  if (dayType === "CUSTOM") {
    const source = day.requirements || {};
    const requirements = {};
    ROLES.forEach((role) => {
      const value = source[role] ?? 0;
      if (!Number.isInteger(value) || value < 0) {
        throw new ScheduleError(`自訂日的 ${role} 人數必須是 0 以上整數`);
      }
      requirements[role] = value;
    });
    const total = ROLES.reduce((sum, role) => sum + requirements[role], 0);
    if (total > availableCount) {
      throw new ScheduleError(`自訂需求共 ${total} 人，但當天只有 ${availableCount} 人可排班`);
    }
    return requirements;
  }

  const aCount = Math.min(2, availableCount);
  const cCount = Math.min(2, Math.max(0, availableCount - aCount));
  const bCount = Math.max(0, availableCount - aCount - cCount);
  return { A: aCount, B: bCount, C: cCount };
}

function optionScore({
  name,
  role,
  dayType,
  previousAssignment,
  roleCounts,
  roleOpportunities,
  assignedCounts,
  availabilityCounts,
  customDay,
  tieNoise,
  config,
}) {
  const opportunity = Math.max(1, roleOpportunities[name][role]);
  const roleRateAfter = (roleCounts[name][role] + 1) / opportunity;
  let score = -4 * roleRateAfter;

  if (customDay) {
    const availability = Math.max(1, availabilityCounts[name]);
    score -= 2.5 * ((assignedCounts[name] + 1) / availability);
  }

  score += Number(config.rolePreferences?.[name]?.[role] || 0);

  if (previousAssignment[name] === "B") {
    const bigMultiplier = dayType === "BIG" ? 1.8 : 1;
    if (role === "A") score += 5 * bigMultiplier;
    else if (role === "C") score += 3 * bigMultiplier;
    else if (role === "B") score -= 6 * bigMultiplier;
  }

  return score + tieNoise;
}

function assignDay({
  day,
  available,
  requirements,
  previousAssignment,
  roleCounts,
  roleOpportunities,
  assignedCounts,
  availabilityCounts,
  random,
  config,
}) {
  const target = ROLES.map((role) => Number(requirements[role]));
  const requiredTotal = target.reduce((sum, count) => sum + count, 0);
  if (requiredTotal === 0) return {};
  if (requiredTotal > available.length) {
    throw new ScheduleError("當日需求人數超過可排班人數");
  }

  const dayType = String(day.day_type || "NORMAL").toUpperCase();
  const customDay = dayType === "CUSTOM";
  const mayLeaveUnassigned = requiredTotal < available.length;
  const noise = {};
  available.forEach((name) => {
    noise[name] = {};
    [...ROLES, "UNASSIGNED"].forEach((role) => {
      noise[name][role] = -0.18 + random() * 0.36;
    });
  });

  let states = new Map([
    ["0,0,0", { counts: [0, 0, 0], score: 0, assignment: {} }],
  ]);

  available.forEach((name) => {
    const nextStates = new Map();
    const choices = allowedRoles(name, config);
    if (mayLeaveUnassigned) choices.push(null);

    states.forEach((current) => {
      choices.forEach((role) => {
        let counts;
        let score;
        let assignment;

        if (role === null) {
          counts = current.counts;
          score = current.score + noise[name].UNASSIGNED;
          assignment = current.assignment;
        } else {
          const roleIndex = ROLES.indexOf(role);
          if (current.counts[roleIndex] >= target[roleIndex]) return;
          counts = [...current.counts];
          counts[roleIndex] += 1;
          score = current.score + optionScore({
            name,
            role,
            dayType,
            previousAssignment,
            roleCounts,
            roleOpportunities,
            assignedCounts,
            availabilityCounts,
            customDay,
            tieNoise: noise[name][role],
            config,
          });
          assignment = { ...current.assignment, [name]: role };
        }

        const key = counts.join(",");
        const previousBest = nextStates.get(key);
        if (!previousBest || score > previousBest.score) {
          nextStates.set(key, { counts, score, assignment });
        }
      });
    });

    states = nextStates;
  });

  const best = states.get(target.join(","));
  if (!best) {
    const needs = ROLES.map((role) => `${role}${requirements[role]}`).join("、");
    throw new ScheduleError(`${day.date || "該日"} 無法滿足角色需求（${needs}），請檢查休假或自訂人數`);
  }
  return best.assignment;
}

export function calculateStats(schedule, vacations, config) {
  const employees = config.employees;
  const vacationSets = Object.fromEntries(
    employees.map((name) => [name, new Set(vacations[name] || [])]),
  );
  const employeeStats = {};
  const streaks = Object.fromEntries(employees.map((name) => [name, 0]));

  employees.forEach((name) => {
    employeeStats[name] = {
      name,
      vacation_days: 0,
      available_days: 0,
      assigned_days: 0,
      unassigned_days: 0,
      role_counts: Object.fromEntries(ROLES.map((role) => [role, 0])),
      consecutive_b_occurrences: 0,
      longest_b_streak: 0,
      ending_b_streak: 0,
      allowed_roles: allowedRoles(name, config),
    };
  });

  let workingDays = 0;
  let bigDays = 0;
  let customDays = 0;
  let offDays = 0;

  schedule.forEach((day) => {
    const date = String(day.date);
    const dayType = String(day.day_type || "NORMAL");
    const assignment = day.assignment || {};

    if (dayType === "OFF") {
      offDays += 1;
      employees.forEach((name) => { streaks[name] = 0; });
      return;
    }

    workingDays += 1;
    if (dayType === "BIG") bigDays += 1;
    if (dayType === "CUSTOM") customDays += 1;

    employees.forEach((name) => {
      const stat = employeeStats[name];
      if (vacationSets[name].has(date)) {
        stat.vacation_days += 1;
        streaks[name] = 0;
        return;
      }

      stat.available_days += 1;
      const role = assignment[name];
      if (!ROLES.includes(role)) {
        stat.unassigned_days += 1;
        streaks[name] = 0;
        return;
      }

      stat.assigned_days += 1;
      stat.role_counts[role] += 1;
      if (role === "B") {
        if (streaks[name] >= 1) stat.consecutive_b_occurrences += 1;
        streaks[name] += 1;
        stat.longest_b_streak = Math.max(stat.longest_b_streak, streaks[name]);
      } else {
        streaks[name] = 0;
      }
    });
  });

  employees.forEach((name) => {
    const stat = employeeStats[name];
    stat.ending_b_streak = streaks[name];
    stat.role_percentages = Object.fromEntries(
      ROLES.map((role) => [
        role,
        stat.assigned_days ? roundTo(stat.role_counts[role] / stat.assigned_days, 4) : 0,
      ]),
    );
  });

  const roleBalance = {};
  ROLES.forEach((role) => {
    const rates = employees
      .map((name) => employeeStats[name])
      .filter((stat) => stat.allowed_roles.includes(role) && stat.available_days > 0)
      .map((stat) => stat.role_counts[role] / stat.available_days);
    const minimum = rates.length ? Math.min(...rates) : 0;
    const maximum = rates.length ? Math.max(...rates) : 0;
    const spread = maximum - minimum;
    roleBalance[role] = {
      min_rate: roundTo(minimum, 4),
      max_rate: roundTo(maximum, 4),
      spread: roundTo(spread, 4),
      score: roundTo(Math.max(0, 100 * (1 - spread)), 1),
    };
  });

  const overallScore = roundTo(
    ROLES.reduce((sum, role) => sum + roleBalance[role].score, 0) / ROLES.length,
    1,
  );

  return {
    period_days: schedule.length,
    working_days: workingDays,
    off_days: offDays,
    big_days: bigDays,
    custom_days: customDays,
    employees: employees.map((name) => employeeStats[name]),
    balance: { overall_score: overallScore, roles: roleBalance },
  };
}

export function generatePeriod(daysInfo, vacations, seed, config) {
  const employees = config.employees;
  const vacationSets = Object.fromEntries(
    employees.map((name) => [name, new Set(vacations[name] || [])]),
  );
  const random = makeRandom(seed);
  const roleCounts = Object.fromEntries(
    employees.map((name) => [name, Object.fromEntries(ROLES.map((role) => [role, 0]))]),
  );
  const roleOpportunities = Object.fromEntries(
    employees.map((name) => [name, Object.fromEntries(ROLES.map((role) => [role, 0]))]),
  );
  const assignedCounts = Object.fromEntries(employees.map((name) => [name, 0]));
  const availabilityCounts = Object.fromEntries(employees.map((name) => [name, 0]));
  let previousAssignment = {};
  const schedule = [];

  daysInfo.forEach((sourceDay, dayOffset) => {
    const day = { ...sourceDay };
    const date = String(day.date);
    const dayType = String(day.day_type || "NORMAL").toUpperCase();
    if (!DAY_TYPES.includes(dayType)) {
      throw new ScheduleError(`${date} 的日期類型不合法`);
    }

    let vacationNames = employees.filter((name) => vacationSets[name].has(date));
    let available = employees.filter((name) => !vacationNames.includes(name));
    let requirements;
    let assignment;
    let unassigned;

    if (dayType === "OFF") {
      requirements = { A: 0, B: 0, C: 0 };
      assignment = {};
      vacationNames = [];
      available = [];
      unassigned = [];
      previousAssignment = {};
    } else {
      requirements = requirementsForDay(day, available.length);
      available.forEach((name) => {
        availabilityCounts[name] += 1;
        allowedRoles(name, config).forEach((role) => {
          if ((requirements[role] || 0) > 0) roleOpportunities[name][role] += 1;
        });
      });

      assignment = assignDay({
        day: { ...day, day_type: dayType },
        available,
        requirements,
        previousAssignment,
        roleCounts,
        roleOpportunities,
        assignedCounts,
        availabilityCounts,
        random,
        config,
      });
      unassigned = available.filter((name) => !Object.hasOwn(assignment, name));

      Object.entries(assignment).forEach(([name, role]) => {
        roleCounts[name][role] += 1;
        assignedCounts[name] += 1;
      });
      previousAssignment = { ...assignment };
    }

    const parsedDate = new Date(`${date}T00:00:00`);
    const weekday = Number.isNaN(parsedDate.getTime())
      ? day.weekday
      : (parsedDate.getDay() + 6) % 7;

    schedule.push({
      day_index: dayOffset + 1,
      date,
      weekday,
      day_type: dayType,
      label: String(day.label || "").trim(),
      requirements,
      assignment,
      vacations: vacationNames,
      unassigned,
    });
  });

  return {
    seed: Number(seed),
    schedule,
    stats: calculateStats(schedule, vacationSets, config),
  };
}
