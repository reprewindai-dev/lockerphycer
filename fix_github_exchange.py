def fix_github_exchange():
    with open('apps/api/routers/auth.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # The current github_exchange function content
    start_idx = content.find('async def github_exchange(')
    end_idx = content.find('return {"access_token": access_token', start_idx)
    end_idx = content.find('\n', end_idx)
    
    new_func = '''async def github_exchange(
    payload: GitHubExchangeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    normalized_email = f"{payload.github_username}@github.veklom.local"
    user = (await db.execute(select(User).where(User.email == normalized_email))).scalars().first()
    if not user:
        user = User(
            email=normalized_email,
            username=payload.github_username,
            full_name=payload.github_username,
            hashed_password="github_oauth_no_password",
            role="user"
        )
        db.add(user)
        await db.flush()
        await db.refresh(user)

    ip_address, user_agent = _request_metadata(request)
    now = datetime.utcnow()
    
    import uuid
    session_id = str(uuid.uuid4())
    
    access_token = create_access_token(
        data={"sub": user.email, "session_id": session_id},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    refresh_token = create_refresh_token(
        data={"sub": user.email, "session_id": session_id},
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    
    session = UserSession(
        id=session_id,
        user_id=user.id,
        session_token=access_token,
        refresh_token=refresh_token,
        ip_address=ip_address,
        user_agent=user_agent,
        expires_at=now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    db.add(session)
    await db.commit()
    
    return {"access_token": access_token, "token_type": "bearer", "user": _user_response(user)}'''

    if start_idx != -1 and end_idx != -1:
        new_content = content[:start_idx] + new_func + content[end_idx:]
        with open('apps/api/routers/auth.py', 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("Replaced github_exchange!")
    else:
        print("Could not find github_exchange to replace!")

fix_github_exchange()
