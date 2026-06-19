"""
Formula-Aware Invertible Synthetic Data Generator for ALCE Risk Scoring

This generator constructs synthetic records from target risk scores backward,
ensuring every record is consistent with the risk formula structure.

Risk Formula Structure:
    R = w0 + Σ wi * fi(xi)
    
Where:
    - w0: intercept (metaModel intercept)
    - wi: factor weights (metaModel coefficients)
    - fi(xi): percentile-scaled feature transformations
"""

import argparse
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from scipy.stats import dirichlet, beta, lognorm


class RiskFormula:
    """Encapsulates the risk formula structure and transformations."""
    
    def __init__(self, params_path: str):
        with open(params_path, 'r') as f:
            params = json.load(f)
        
        self.w0 = params['metaModel']['intercept']
        self.weights = params['metaModel']['coefficients']
        self.scaling = params['scaling']
        self.factor_columns = {
            'weather': ['precipitation', 'wind_speed', 'visibility'],
            'traffic': ['traffic_index', 'incident_flag'],
            'fleet': ['fleet_utilization'],
            'driver': ['driver_fatigue', 'driver_availability'],
            'warehouse': ['warehouse_dock_util', 'warehouse_queue_time']
        }
        self.factors = list(self.weights.keys())
    
    def compute_score(self, features: Dict[str, np.ndarray]) -> np.ndarray:
        """Compute risk score from raw features using the formula."""
        factor_scores = {}
        
        for factor in self.factors:
            cols = self.factor_columns[factor]
            # Compute mean of features for this factor
            if len(cols) == 1:
                raw = features[cols[0]]
            else:
                raw = np.mean([features[col] for col in cols], axis=0)
            
            # Apply percentile scaling
            p5 = self.scaling[factor]['p5']
            p95 = self.scaling[factor]['p95']
            scaled = (raw - p5) / (p95 - p5)
            scaled = np.clip(scaled, 0, 1)
            factor_scores[factor] = scaled
        
        # Compute weighted sum
        score = self.w0
        for factor in self.factors:
            score += self.weights[factor] * factor_scores[factor]
        
        return score, factor_scores
    
    def invert_transform(self, factor: str, scaled_value: np.ndarray) -> np.ndarray:
        """Invert percentile scaling to get raw feature value."""
        p5 = self.scaling[factor]['p5']
        p95 = self.scaling[factor]['p95']
        raw = scaled_value * (p95 - p5) + p5
        return raw


class InvertibleGenerator:
    """Formula-aware invertible synthetic data generator."""
    
    def __init__(self, formula: RiskFormula, seed: int = 42):
        self.formula = formula
        self.rng = np.random.RandomState(seed)
        self.alpha = 1.0  # Dirichlet concentration parameter
        self.noise_scale = 0.02  # Noise injection scale (reduced for better alignment)
    
    def sample_target_score(
        self, 
        n: int, 
        distribution: str = 'uniform',
        tail_stress: float = 0.1
    ) -> np.ndarray:
        """
        Sample target risk scores from a controllable distribution.
        
        Args:
            n: Number of samples
            distribution: 'uniform', 'realistic', 'lognormal', 'beta'
            tail_stress: Fraction of samples to force into tails
        """
        # Calculate max possible score based on formula bounds
        max_score = self.formula.w0 + sum(self.formula.weights.values())
        min_score = self.formula.w0  # Minimum when all scaled features are 0
        
        if distribution == 'uniform':
            # Uniform across realistic score range (not full theoretical range)
            scores = self.rng.uniform(min_score, min_score + 3.0, size=n)
        elif distribution == 'realistic':
            # Beta distribution for realistic skew
            scores = beta.rvs(2, 5, loc=min_score, scale=max_score-min_score, size=n, random_state=self.rng)
        elif distribution == 'lognormal':
            # Log-normal for heavy tails
            scores = lognorm.rvs(0.5, loc=min_score, scale=(max_score-min_score)/3, size=n, random_state=self.rng)
            scores = np.clip(scores, min_score, max_score)
        elif distribution == 'beta':
            # Beta for bounded distribution
            scores = beta.rvs(2, 2, loc=min_score, scale=max_score-min_score, size=n, random_state=self.rng)
        else:
            raise ValueError(f"Unknown distribution: {distribution}")
        
        # Stress tails explicitly
        n_tail = int(n * tail_stress)
        if n_tail > 0:
            tail_indices = self.rng.choice(n, n_tail, replace=False)
            # Half high tail, half low tail
            high_tail = tail_indices[:n_tail//2]
            low_tail = tail_indices[n_tail//2:]
            scores[high_tail] = self.rng.uniform(max_score * 0.8, max_score, size=len(high_tail))
            scores[low_tail] = self.rng.uniform(min_score, min_score + (max_score-min_score) * 0.2, size=len(low_tail))
        
        return scores
    
    def allocate_contributions(
        self, 
        target_scores: np.ndarray,
        sparsity_mode: str = 'balanced'
    ) -> Dict[str, np.ndarray]:
        """
        Allocate contribution budget using Dirichlet distribution.
        
        Args:
            target_scores: Target risk scores
            sparsity_mode: 'balanced', 'sparse', 'dominant'
        
        Returns:
            Dictionary of factor contributions (scaled values in [0,1])
        """
        n = len(target_scores)
        factors = self.formula.factors
        n_factors = len(factors)
        
        # Set alpha based on sparsity mode
        if sparsity_mode == 'balanced':
            alpha = np.ones(n_factors)
        elif sparsity_mode == 'sparse':
            alpha = 0.3 * np.ones(n_factors)
        elif sparsity_mode == 'dominant':
            alpha = np.array([3.0] + [0.5] * (n_factors - 1))
        else:
            alpha = self.alpha * np.ones(n_factors)
        
        # Sample Dirichlet for contribution proportions
        proportions = dirichlet.rvs(alpha, size=n, random_state=self.rng)
        
        # Compute contributions
        # The formula is: R = w0 + Σ wi * fi(xi)
        # So: Σ wi * fi(xi) = target_score - w0
        # We allocate proportions of the budget to each factor's weighted contribution
        contributions = {}
        budget = target_scores - self.formula.w0
        
        for i, factor in enumerate(factors):
            weight = self.formula.weights[factor]
            # Weighted contribution for this factor
            weighted_contrib = proportions[:, i] * budget
            # Scaled feature value = weighted contribution / weight
            scaled_value = weighted_contrib / weight
            
            # Clip to [0, 1] since these are scaled feature values
            contributions[factor] = np.clip(scaled_value, 0, 1)
        
        return contributions
    
    def invert_features(
        self, 
        contributions: Dict[str, np.ndarray]
    ) -> Dict[str, np.ndarray]:
        """
        Invert feature transformations to get raw feature values.
        
        Args:
            contributions: Dictionary of factor contributions (these are the scaled values)
        
        Returns:
            Dictionary of raw feature values
        """
        features = {}
        
        for factor, contrib in contributions.items():
            # Ensure contributions are non-negative (clipped at 0)
            contrib = np.maximum(contrib, 0)
            
            # Invert scaling to get raw factor value
            raw_factor = self.formula.invert_transform(factor, contrib)
            
            # Distribute across individual features
            cols = self.formula.factor_columns[factor]
            if len(cols) == 1:
                features[cols[0]] = raw_factor
            else:
                # Distribute evenly without noise for precise inversion
                base = raw_factor / len(cols)
                for col in cols:
                    features[col] = base.copy()
        
        return features
    
    def apply_constraints(self, features: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
        """
        Apply hard and soft constraints to ensure valid feature combinations.
        
        Hard constraints:
        - utilization ∈ [0,1]
        - balances ≥ 0
        - visibility ∈ [0.5, 10]
        
        Soft constraints (correlations):
        - if traffic high → reduce driver availability
        - if warehouse queue long → increase dock utilization
        """
        n = len(next(iter(features.values())))
        
        # Hard constraints
        features['traffic_index'] = np.clip(features['traffic_index'], 0, 1)
        features['incident_flag'] = np.clip(features['incident_flag'], 0, 1)
        features['fleet_utilization'] = np.clip(features['fleet_utilization'], 0, 1)
        features['driver_fatigue'] = np.clip(features['driver_fatigue'], 0, 1)
        features['driver_availability'] = np.clip(features['driver_availability'], 0, 1)
        features['warehouse_dock_util'] = np.clip(features['warehouse_dock_util'], 0, 1)
        features['warehouse_queue_time'] = np.maximum(features['warehouse_queue_time'], 0)
        features['visibility'] = np.clip(features['visibility'], 0.5, 10)
        features['precipitation'] = np.maximum(features['precipitation'], 0)
        features['wind_speed'] = np.maximum(features['wind_speed'], 0)
        
        # Soft constraints using conditional rules (made less aggressive)
        # High traffic → lower driver availability
        high_traffic = features['traffic_index'] > 0.7
        features['driver_availability'][high_traffic] *= 0.9
        
        # Long warehouse queue → higher dock utilization
        long_queue = features['warehouse_queue_time'] > 40
        features['warehouse_dock_util'][long_queue] = np.clip(
            features['warehouse_dock_util'][long_queue] * 1.1, 0, 1
        )
        
        # High fleet utilization → higher driver fatigue
        high_util = features['fleet_utilization'] > 0.8
        features['driver_fatigue'][high_util] = np.clip(
            features['driver_fatigue'][high_util] * 1.1, 0, 1
        )
        
        return features
    
    def inject_noise(
        self, 
        features: Dict[str, np.ndarray],
        noise_mode: str = 'gaussian'
    ) -> Tuple[Dict[str, np.ndarray], Dict[str, np.ndarray]]:
        """
        Inject controlled noise to avoid overfitting to perfect formula.
        
        Args:
            features: Raw feature values
            noise_mode: 'gaussian', 'percentile', 'none'
        
        Returns:
            Tuple of (noisy_features, noise_delta)
        """
        noisy_features = {}
        noise_delta = {}
        
        for col, values in features.items():
            if noise_mode == 'gaussian':
                noise = self.rng.normal(0, self.noise_scale * np.std(values), size=len(values))
            elif noise_mode == 'percentile':
                noise = self.rng.normal(0, 0.02, size=len(values)) * values
            else:
                noise = np.zeros_like(values)
            
            noisy_features[col] = values + noise
            noise_delta[col] = noise
        
        return noisy_features, noise_delta
    
    def generate_labels(
        self, 
        scores: np.ndarray,
        threshold: Optional[float] = None,
        probabilistic: bool = False
    ) -> np.ndarray:
        """
        Generate labels from risk scores.
        
        Args:
            scores: Risk scores
            threshold: Classification threshold (default: median)
            probabilistic: If True, return probabilities
        
        Returns:
            Labels or probabilities
        """
        if threshold is None:
            threshold = np.median(scores)
        
        if probabilistic:
            # Sigmoid transformation
            probs = 1 / (1 + np.exp(-scores))
            return probs
        else:
            return (scores > threshold).astype(int)
    
    def generate(
        self,
        n: int = 10000,
        score_distribution: str = 'uniform',
        sparsity_mode: str = 'balanced',
        noise_mode: str = 'gaussian',
        tail_stress: float = 0.1,
        coverage_mode: str = 'full'
    ) -> pd.DataFrame:
        """
        Generate synthetic records using inverse-driven generation.
        
        Args:
            n: Number of records to generate
            score_distribution: Distribution for target scores
            sparsity_mode: Dirichlet sparsity mode
            noise_mode: Noise injection mode
            tail_stress: Fraction of tail samples
            coverage_mode: 'full', 'normal', 'tails'
        
        Returns:
            DataFrame with raw features, contributions, and scores
        """
        # Step A: Sample target risk scores
        target_scores = self.sample_target_score(
            n, distribution=score_distribution, tail_stress=tail_stress
        )
        
        # Coverage controls
        if coverage_mode == 'tails':
            # Force more tail coverage
            target_scores[:n//5] = self.rng.uniform(2.0, 3.0, size=n//5)
            target_scores[n//5:2*n//5] = self.rng.uniform(0.0, 0.5, size=n//5)
        elif coverage_mode == 'normal':
            # Focus on normal range
            target_scores = self.rng.uniform(0.5, 2.0, size=n)
        
        # Step B: Allocate contribution budget
        contributions = self.allocate_contributions(target_scores, sparsity_mode=sparsity_mode)
        
        # Step C: Invert feature transformations
        features = self.invert_features(contributions)
        
        # Step D: Apply constraints
        features = self.apply_constraints(features)
        
        # Step E: Inject noise
        noisy_features, noise_delta = self.inject_noise(features, noise_mode=noise_mode)
        
        # Recompute final score
        final_score, final_factor_scores = self.formula.compute_score(noisy_features)
        
        # Track deviation
        score_deviation = final_score - target_scores
        
        # Generate labels
        labels = self.generate_labels(final_score)
        
        # Build output DataFrame
        output = pd.DataFrame(noisy_features)
        
        # Add transformed features
        for factor, scores in final_factor_scores.items():
            output[f'{factor}_score'] = scores
        
        # Add contributions
        for factor, contrib in contributions.items():
            output[f'{factor}_contribution'] = contrib
        
        # Add scores and metadata
        output['target_score'] = target_scores
        output['final_score'] = final_score
        output['score_deviation'] = score_deviation
        output['label'] = labels
        
        # Add noise tracking
        for col, delta in noise_delta.items():
            output[f'{col}_noise'] = delta
        
        return output


def main():
    parser = argparse.ArgumentParser(
        description='Generate formula-aware invertible synthetic data for ALCE calibration'
    )
    parser.add_argument('--params', default='calibration/params.json', help='Path to calibration parameters')
    parser.add_argument('--n', type=int, default=10000, help='Number of samples to generate')
    parser.add_argument('--output', default='calibration/synthetic_invertible.csv', help='Output CSV path')
    parser.add_argument('--score-distribution', choices=['uniform', 'realistic', 'lognormal', 'beta'],
                        default='uniform', help='Target score distribution')
    parser.add_argument('--sparsity-mode', choices=['balanced', 'sparse', 'dominant'],
                        default='balanced', help='Dirichlet sparsity mode')
    parser.add_argument('--noise-mode', choices=['gaussian', 'percentile', 'none'],
                        default='gaussian', help='Noise injection mode')
    parser.add_argument('--tail-stress', type=float, default=0.1,
                        help='Fraction of samples to force into tails')
    parser.add_argument('--coverage-mode', choices=['full', 'normal', 'tails'],
                        default='full', help='Coverage control mode')
    parser.add_argument('--seed', type=int, default=42, help='Random seed')
    args = parser.parse_args()
    
    # Load formula
    formula = RiskFormula(args.params)
    
    # Create generator
    generator = InvertibleGenerator(formula, seed=args.seed)
    
    # Generate data
    df = generator.generate(
        n=args.n,
        score_distribution=args.score_distribution,
        sparsity_mode=args.sparsity_mode,
        noise_mode=args.noise_mode,
        tail_stress=args.tail_stress,
        coverage_mode=args.coverage_mode
    )
    
    # Save output
    df.to_csv(args.output, index=False)
    print(f'Generated {len(df)} invertible synthetic records to {args.output}')
    print(f'Score range: [{df["final_score"].min():.3f}, {df["final_score"].max():.3f}]')
    print(f'Mean score deviation: {df["score_deviation"].abs().mean():.3f}')
    print(f'Label distribution: {df["label"].value_counts().to_dict()}')


if __name__ == '__main__':
    main()
