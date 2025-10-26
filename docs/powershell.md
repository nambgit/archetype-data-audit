# Edit last files access days - Powershell

$file = "C:\Users\YourUsername\Desktop\testfile.txt"
$date = (Get-Date).AddDays(-180)
(Get-Item $file).CreationTime = $date
(Get-Item $file).LastWriteTime = $date
(Get-Item $file).LastAccessTime = $date



