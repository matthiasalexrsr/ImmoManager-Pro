import { describe, expect, it } from 'vitest';
import { buildDashboardWorkflow } from '../utils/dashboardWorkflow.js';

describe('DashboardWorkflow', () => {
  it('guides the core process to the next missing setup step', () => {
    const { processSteps, nextStep } = buildDashboardWorkflow({
      stats: {
        properties: 1,
        units: 2,
      },
    });

    expect(processSteps.map(step => step.id)).toEqual([
      'property',
      'unit',
      'tenant',
      'contract',
      'charge',
      'payment',
      'dunning',
    ]);
    expect(processSteps.find(step => step.id === 'property').status).toBe('done');
    expect(processSteps.find(step => step.id === 'unit').status).toBe('done');
    expect(nextStep.id).toBe('process-tenant');
    expect(nextStep.to).toBe('/tenants');
  });

  it('marks the portfolio workflow as complete when core inventory exists', () => {
    const { workflows } = buildDashboardWorkflow({
      stats: {
        portfolios: 1,
        properties: 2,
        units: 4,
        unitsOccupied: 3,
        unitsReserved: 0,
      },
    });

    const portfolio = workflows.find(item => item.id === 'portfolio');
    expect(portfolio.progress).toBe(100);
    expect(portfolio.status).toBe('complete');
    expect(portfolio.actionTo).toBe('/units');
  });

  it('raises finance attention for aged or open receivables', () => {
    const { workflows, attentionItems } = buildDashboardWorkflow({
      stats: {
        accounts: 1,
        rentCharges: 2,
        openReceivables: 3,
      },
      aging: {
        openTotal: 3,
        buckets: {
          current: 0,
          days1to30: 100,
          days31to60: 0,
          days61to90: 0,
          days90plus: 0,
        },
      },
    });

    const finance = workflows.find(item => item.id === 'finance');
    expect(finance.status).toBe('attention');
    expect(finance.actionTo).toBe('/receivables');
    expect(attentionItems.map(item => item.id)).toContain('overdue-receivables');
    expect(attentionItems.map(item => item.id)).toContain('open-receivables');
  });

  it('raises operational attention for dunning, billing preflight, documents, and escalations', () => {
    const { workflows, attentionItems, nextStep } = buildDashboardWorkflow({
      stats: {
        properties: 1,
        units: 1,
        tenants: 1,
        contractsActive: 1,
        rentCharges: 1,
        openReceivables: 2,
        overdueReceivables: 1,
        dunningReceivables: 1,
        billingPeriods: 1,
        allocationKeys: 1,
        billingPreflightBlockers: 1,
        documents: 1,
        missingContractDocuments: 1,
        openMaintenance: 1,
        overdueMaintenance: 1,
        maintenanceEscalationCandidates: 1,
      },
    });

    const ids = attentionItems.map(item => item.id);
    expect(ids).toContain('dunning-receivables');
    expect(ids).toContain('billing-preflight-blockers');
    expect(ids).toContain('maintenance-escalations');
    expect(ids).toContain('missing-contract-documents');
    expect(workflows.find(item => item.id === 'billing').status).toBe('attention');
    expect(workflows.find(item => item.id === 'operations').status).toBe('attention');
    expect(nextStep.id).toBe('process-payment');
    expect(nextStep.tone).toBe('attention');
  });

  it('returns an empty attention queue when no operational blockers exist', () => {
    const { attentionItems } = buildDashboardWorkflow({
      stats: {
        openReceivables: 0,
        overdueReceivables: 0,
        openMaintenance: 0,
        openTasks: 0,
        unreadNotifications: 0,
      },
      aging: {
        openTotal: 0,
        buckets: {
          current: 0,
          days1to30: 0,
          days31to60: 0,
          days61to90: 0,
          days90plus: 0,
        },
      },
      expiring: { contracts: [] },
    });

    expect(attentionItems).toEqual([]);
  });
});
