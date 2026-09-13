def fix_security_auth():
    with open('core/security/auth.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    old_line = 'payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])'
    new_line = 'payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"], audience="veklom-cappo")'
    
    if old_line in content:
        content = content.replace(old_line, new_line)
        with open('core/security/auth.py', 'w', encoding='utf-8') as f:
            f.write(content)
        print('Fixed core/security/auth.py!')
    else:
        print('Could not find verify_token decode line!')

fix_security_auth()
