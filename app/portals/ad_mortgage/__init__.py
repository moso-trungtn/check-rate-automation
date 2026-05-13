"""Side-effect: importing this package registers the AD Mortgage adapter."""

from app.portals.ad_mortgage.adapter import AdMortgageAdapter

__all__ = ["AdMortgageAdapter"]
