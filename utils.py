def calculate_score_weights(
    account_age_years: float,
    followers: int,
    tweets: int,
    is_verified: bool,
    is_active: bool,
    engagement: str,
    positives: int,
    complaints: int,
    pinned_has_url: bool
) -> dict[str, int]:
    """
    统一的评分明细测算函数，确保文本模板与图片展现双端一致
    """
    # 边界下限防护
    account_age_years = max(0.0, account_age_years)
    followers = max(0, followers)
    tweets = max(0, tweets)
    positives = max(0, positives)
    complaints = max(0, complaints)

    b_age = min(25, int(account_age_years * 1.5))
    
    if followers > 1000000:
        b_fol = 20
    elif followers > 100000:
        b_fol = 15
    elif followers > 10000:
        b_fol = 10
    else:
        b_fol = 5
    
    if tweets > 10000:
        b_twt = 8
    elif tweets > 1000:
        b_twt = 5
    else:
        b_twt = 2
    
    b_ver = 10 if is_verified else 0
    b_act = 5 if is_active else 0
    
    if engagement == "high":
        b_eng = 8
    elif engagement == "medium":
        b_eng = 5
    else:
        b_eng = 2
    
    if positives >= 10:
        b_pos = 10
    elif positives >= 5:
        b_pos = 8
    elif positives >= 1:
        b_pos = 5
    else:
        b_pos = 0
    
    if complaints >= 5:
        b_neg = -15
    elif complaints >= 3:
        b_neg = -10
    elif complaints >= 1:
        b_neg = -5
    else:
        b_neg = 0
    
    b_pin = -10 if pinned_has_url else 0
    
    return {
        "b_age": b_age,
        "b_fol": b_fol,
        "b_twt": b_twt,
        "b_ver": b_ver,
        "b_act": b_act,
        "b_eng": b_eng,
        "b_pos": b_pos,
        "b_neg": b_neg,
        "b_pin": b_pin
    }
