export interface Scenario {
  id: string;
  name: string;
  initialInvestment: number;
  monthlyContribution: number;
  annualRate: number;
  years: number;
  compoundingFrequency: number; // times per year
}

export interface DataPoint {
  year: number;
  totalPrincipal: number;
  totalInterest: number;
  totalValue: number;
  monthlyContributionSnapshot: number;
}
