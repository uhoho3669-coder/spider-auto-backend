$headers = @{
    'Authorization' = 'Bearer rnd_yDSgm4uGQpdCQ036njXbmrMXHuvo'
    'Content-Type'  = 'application/json'
    'Accept'        = 'application/json'
}

$body = @{
    type       = 'web_service'
    name       = 'spider-auto-backend'
    ownerId    = 'tea-d9loa5u7bikc739dqo80'
    repo       = 'https://github.com/uhoho3669-coder/spider-auto-backend'
    branch     = 'master'
    autoDeploy = 'yes'
    serviceDetails = @{
        envSpecificDetails = @{
            buildCommand = 'pip install -r requirements.txt && pip install flask'
            startCommand = 'python app.py'
        }
        plan    = 'free'
        runtime = 'python'
        region  = 'oregon'
    }
} | ConvertTo-Json -Depth 5

$response = Invoke-RestMethod -Uri 'https://api.render.com/v1/services' -Headers $headers -Method Post -Body $body
$response | ConvertTo-Json -Depth 10
