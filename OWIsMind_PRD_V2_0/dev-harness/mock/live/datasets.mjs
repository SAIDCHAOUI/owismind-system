// The three synthetic datasets of the LIVE harness mode (DRIVE_Revenues,
// TroubleTickets_year, Opportunities_Won). 100 % fake and deterministic (seeded
// PRNG): no real account, revenue, ticket or deal ever appears. Pure JS, shared by
// the main thread (Source Data / Evidence engine) and the SQL worker (agent SQL),
// which both build the SAME rows from the same seeds.

import { mulberry32 } from '../data.mjs'

export const PROJECT_KEY = 'OWISMIND_DEV'

const ACCOUNTS = [
  { name: 'Global Telecom Partners', partner: 'Direct', dist: 'Direct' },
  { name: 'Nordic Carrier AB', partner: 'Direct', dist: 'Direct' },
  { name: 'Iberia Connect SA', partner: 'Atlas Reseller Group', dist: 'Indirect' },
  { name: 'Pacific Wholesale Ltd', partner: 'Direct', dist: 'Direct' },
  { name: 'Atlantic Networks Inc', partner: 'Meridian Channel Co', dist: 'Indirect' },
  { name: 'Sahara Telecom Group', partner: 'Direct', dist: 'Direct' },
  { name: 'Danube Mobile Kft', partner: 'Atlas Reseller Group', dist: 'Indirect' },
  { name: 'Levant Communications', partner: 'Direct', dist: 'Direct' },
  { name: 'Andes Fibra SpA', partner: 'Meridian Channel Co', dist: 'Indirect' },
  { name: 'Baltic Signal OU', partner: 'Direct', dist: 'Direct' },
  { name: 'Coral Islands Telecom', partner: 'Lagoon Partners', dist: 'Indirect' },
  { name: 'Alpine Carrier AG', partner: 'Direct', dist: 'Direct' },
  { name: 'Savanna Mobile Ltd', partner: 'Lagoon Partners', dist: 'Indirect' },
  { name: 'Aurora Networks Oy', partner: 'Direct', dist: 'Direct' },
]

// SolutionLine > Solution > Product (the offer hierarchy of the real base).
const OFFERS = [
  { line: 'Voice', solution: 'Voice Termination', product: 'International Voice' },
  { line: 'Voice', solution: 'Voice Termination', product: 'Premium Voice' },
  { line: 'Voice', solution: 'Voice Hubbing', product: 'Voice Hub' },
  { line: 'Messaging', solution: 'SMS A2P', product: 'A2P Gateway' },
  { line: 'Messaging', solution: 'SMS P2P', product: 'P2P Hub' },
  { line: 'Mobility', solution: 'Roaming Data', product: 'Data Roaming Sponsored' },
  { line: 'Mobility', solution: 'Signaling', product: 'SCCP Signaling' },
  { line: 'Data', solution: 'IPX Transit', product: 'IPX Premium' },
  { line: 'Data', solution: 'IP Transit', product: 'IP Transit Global' },
  { line: 'Infrastructure', solution: 'Capacity Leasing', product: 'Submarine Capacity' },
  { line: 'Infrastructure', solution: 'Colocation', product: 'Data Center Colocation' },
]

const pad = (n) => String(n).padStart(2, '0')
const round2 = (n) => Math.round(n * 100) / 100

// Monthly periods 2024-01 .. 2026-09 as 'YYYY-MM-01'.
function periods() {
  const out = []
  for (let y = 2024; y <= 2026; y++) {
    for (let m = 1; m <= 12; m++) {
      if (y === 2026 && m > 9) break
      out.push({ y, m, date: `${y}-${pad(m)}-01` })
    }
  }
  return out
}

// Which phases exist for a period: ACTUALS up to 2026-08 (last closed month),
// BUDGET from 2025, FORECAST over 2026, HLF (half-year landing) from 2026-04,
// Q3F (Q3 forecast) over 2026 Q3.
function phasesFor(p) {
  const ym = p.y * 100 + p.m
  const out = []
  if (ym <= 202608) out.push('ACTUALS')
  if (p.y >= 2025) out.push('BUDGET')
  if (p.y === 2026) out.push('FORECAST')
  if (ym >= 202604) out.push('HLF')
  if (ym >= 202607) out.push('Q3F')
  return out
}

export const REVENUE_COLUMNS = [
  { name: 'diamond_id', type: 'bigint' },
  { name: 'Account_name', type: 'string' },
  { name: 'Account_partner', type: 'string' },
  { name: 'distribution_type', type: 'string' },
  { name: 'SolutionLine', type: 'string' },
  { name: 'Solution', type: 'string' },
  { name: 'Product', type: 'string' },
  { name: 'Phase', type: 'string' },
  { name: 'booking_type', type: 'string' },
  { name: 'period', type: 'date' },
  { name: 'revenue', type: 'double' },
]

function buildRevenues() {
  const rng = mulberry32(20261021)
  // 3 offers per account (stable), so 42 (account, offer) pairs x 71 phase-months.
  const pairs = []
  for (const account of ACCOUNTS) {
    const picked = new Set()
    while (picked.size < 3) picked.add(Math.floor(rng() * OFFERS.length))
    for (const i of picked) pairs.push({ account, offer: OFFERS[i], base: 20000 + rng() * 380000, growth: -0.04 + rng() * 0.16 })
  }
  const rows = []
  let id = 700000
  for (const p of periods()) {
    const t = (p.y - 2024) + (p.m - 1) / 12
    const season = 1 + 0.1 * Math.sin((p.m / 12) * Math.PI * 2)
    for (const pair of pairs) {
      const trend = pair.base * season * (1 + pair.growth * t)
      for (const phase of phasesFor(p)) {
        const factor = phase === 'ACTUALS' ? 0.85 + rng() * 0.3
          : phase === 'BUDGET' ? 1.02 + rng() * 0.1
            : 0.92 + rng() * 0.16
        rows.push({
          diamond_id: ++id,
          Account_name: pair.account.name,
          Account_partner: pair.account.partner,
          distribution_type: pair.account.dist,
          SolutionLine: pair.offer.line,
          Solution: pair.offer.solution,
          Product: pair.offer.product,
          Phase: phase,
          booking_type: rng() < 0.7 ? 'Accrual' : 'Bill',
          period: p.date,
          revenue: round2(trend * factor),
        })
      }
    }
  }
  return rows
}

export const TICKET_COLUMNS = [
  { name: 'id', type: 'bigint' },
  { name: 'Account_name', type: 'string' },
  { name: 'Severity', type: 'string' },
  { name: 'Status', type: 'string' },
  { name: 'Category', type: 'string' },
  { name: 'Product', type: 'string' },
  { name: 'creationDate', type: 'date' },
  { name: 'closedDate', type: 'date' },
  { name: 'resolution_hours', type: 'double' },
]

const CATEGORIES = ['Quality of Service', 'Billing Dispute', 'Provisioning', 'Outage', 'Routing']

function buildTickets() {
  const rng = mulberry32(20261022)
  const rows = []
  const start = Date.UTC(2025, 0, 1)
  const end = Date.UTC(2026, 8, 30)
  const day = 86400000
  for (let i = 0; i < 1500; i++) {
    const opened = start + Math.floor(rng() * ((end - start) / day)) * day
    const r = rng()
    const severity = r < 0.08 ? 'P1' : r < 0.3 ? 'P2' : r < 0.7 ? 'P3' : 'P4'
    const ageDays = (end - opened) / day
    // Recent tickets are more likely still open.
    const openChance = ageDays < 30 ? 0.6 : ageDays < 90 ? 0.25 : 0.04
    const s = rng()
    const status = s < openChance * 0.5 ? 'Open' : s < openChance ? 'In Progress' : rng() < 0.4 ? 'Resolved' : 'Closed'
    const closed = status === 'Resolved' || status === 'Closed'
    const scale = { P1: 8, P2: 30, P3: 70, P4: 140 }[severity]
    const hours = closed ? round2(1 + rng() * scale * 1.6) : null
    const offer = OFFERS[Math.floor(rng() * OFFERS.length)]
    rows.push({
      id: 900000 + i + 1,
      Account_name: ACCOUNTS[Math.floor(rng() * ACCOUNTS.length)].name,
      Severity: severity,
      Status: status,
      Category: CATEGORIES[Math.floor(rng() * CATEGORIES.length)],
      Product: offer.product,
      creationDate: new Date(opened).toISOString().slice(0, 10),
      closedDate: closed ? new Date(opened + Math.ceil(hours / 24) * day).toISOString().slice(0, 10) : null,
      resolution_hours: hours,
    })
  }
  return rows
}

export const OPPORTUNITY_COLUMNS = [
  { name: 'opportunity_id', type: 'bigint' },
  { name: 'Account_name', type: 'string' },
  { name: 'SolutionLine', type: 'string' },
  { name: 'Solution', type: 'string' },
  { name: 'Product', type: 'string' },
  { name: 'sales_region', type: 'string' },
  { name: 'won_date', type: 'date' },
  { name: 'contract_months', type: 'bigint' },
  { name: 'amount_eur', type: 'double' },
]

function buildOpportunities() {
  const rng = mulberry32(20261023)
  const regions = ['EMEA', 'APAC', 'AMER']
  const rows = []
  const start = Date.UTC(2024, 0, 1)
  const end = Date.UTC(2026, 8, 30)
  const day = 86400000
  for (let i = 0; i < 500; i++) {
    const won = start + Math.floor(rng() * ((end - start) / day)) * day
    const offer = OFFERS[Math.floor(rng() * OFFERS.length)]
    const months = [12, 24, 36][Math.floor(rng() * 3)]
    rows.push({
      opportunity_id: 400000 + i + 1,
      Account_name: ACCOUNTS[Math.floor(rng() * ACCOUNTS.length)].name,
      SolutionLine: offer.line,
      Solution: offer.solution,
      Product: offer.product,
      sales_region: regions[Math.floor(rng() * regions.length)],
      won_date: new Date(won).toISOString().slice(0, 10),
      contract_months: months,
      amount_eur: round2((50000 + rng() * 1950000) * (months / 24)),
    })
  }
  return rows
}

// The live datasets registry: logical dataset -> physical table (project key first,
// like DSS managed SQL datasets) + columns + rows. Order = Source Data source ids.
export function buildLiveDatasets() {
  return [
    { key: 'revenues', dataset: 'DRIVE_Revenues', label: 'DRIVE Revenues', table: `${PROJECT_KEY}_drive_revenues`, columns: REVENUE_COLUMNS, rows: buildRevenues() },
    { key: 'tickets', dataset: 'TroubleTickets_year', label: 'Trouble Tickets', table: `${PROJECT_KEY}_troubletickets_year`, columns: TICKET_COLUMNS, rows: buildTickets() },
    { key: 'opportunities', dataset: 'Opportunities_Won', label: 'Opportunities Won', table: `${PROJECT_KEY}_opportunities_won`, columns: OPPORTUNITY_COLUMNS, rows: buildOpportunities() },
  ]
}
