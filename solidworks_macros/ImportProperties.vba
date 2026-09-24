' ******************************************************************************
' SolidWorks Custom Property Import Macro
' ******************************************************************************
'
' AMAC:
'   Google Sheets'ten export edilen CSV dosyasini okuyarak, acik montaj
'   dosyasindaki bilesenlerin Custom Properties degerlerini gunceller.
'
' GUNCELLENEN CUSTOM PROPERTIES (6 adet):
'   uretim_sekli, malzeme, malzeme_ebat, alt_kod, revizyon, tarih
'
' CSV FORMATI: Noktali virgul (;) ayracli, UTF-8, 9 sutun
'   Sütun 0: Parent Ref
'   Sütun 1: Child Ref (eslestirme anahtari)
'   Sütun 2: Miktar
'   Sütun 3-8: Custom Properties (uretim_sekli ~ tarih)
'
' KULLANIM:
'   1. SolidWorks'te montaj dosyasini acin
'   2. Bu makroyu calistirin
'   3. Google Sheets'ten indirilen CSV dosyasini secin
'   4. Custom Properties otomatik guncellenecektir
' ******************************************************************************

Option Explicit

' Custom Property Sabitleri
Const CP_URETIM_SEKLI As String = "uretim_sekli"
Const CP_MALZEME As String = "malzeme"
Const CP_MALZEME_EBAT As String = "malzeme_ebat"
Const CP_ALT_KOD As String = "alt_kod"
Const CP_REVIZYON As String = "revizyon"
Const CP_TARIH As String = "tarih"

' CSV Sutun Indeksleri
Const CSV_CHILD_REF As Long = 1
Const CSV_URETIM_SEKLI As Long = 3
Const CSV_MALZEME As Long = 4
Const CSV_MALZEME_EBAT As Long = 5
Const CSV_ALT_KOD As Long = 6
Const CSV_REVIZYON As Long = 7
Const CSV_TARIH As Long = 8

' Istatistik Degiskenleri
Dim updatedCount As Long
Dim skippedCount As Long
Dim notFoundCount As Long
Dim errorCount As Long
Dim detailLog As String

Sub main()
    On Error GoTo ErrorHandler
    
    Dim startTime As Double
    startTime = Timer
    
    ' --- BASLANGIC KONTROLLER ---
    Dim swApp As Object
    Dim swModel As Object
    Set swApp = Application.SldWorks
    Set swModel = swApp.ActiveDoc
    
    If swModel Is Nothing Then
        MsgBox "Lütfen bir montaj dosyasi açin.", vbCritical, "Hata"
        Exit Sub
    End If
    
    If swModel.GetType <> 2 Then  ' swDocASSEMBLY
        MsgBox "Bu makro sadece montaj dosyalarinda çalisir.", vbCritical, "Hata"
        Exit Sub
    End If
    
    ' --- DOSYA SEC ---
    Dim filePath As String
    filePath = SelectCSVFile()
    If filePath = "" Then Exit Sub
    
    ' --- CSV OKU ---
    Dim csvData As Object  ' Dictionary: childRef -> Array of CP values
    Set csvData = ReadCSVFile(filePath)
    
    If csvData.count = 0 Then
        MsgBox "CSV dosyasinda geçerli veri bulunamadi!", vbExclamation, "Uyari"
        Exit Sub
    End If
    
    ' --- PERFORMANS ---
    Dim resolveResult As Long
    resolveResult = swModel.ResolveAllLightWeightComponents(False)
    
    Dim swModelView As Object
    Set swModelView = swModel.ActiveView
    If Not swModelView Is Nothing Then
        swModelView.EnableGraphicsUpdate = False
    End If
    
    ' --- SAYACLARI SIFIRLA ---
    updatedCount = 0
    skippedCount = 0
    notFoundCount = 0
    errorCount = 0
    detailLog = ""
    
    ' --- MONTAJ AGACINI TARA VE GUNCELLE ---
    Dim swConf As Object
    Dim swRootComp As Object
    Set swConf = swModel.GetActiveConfiguration
    Set swRootComp = swConf.GetRootComponent3(True)
    
    If swRootComp Is Nothing Then
        MsgBox "Kök bilesen alinamadi!", vbCritical, "Hata"
        If Not swModelView Is Nothing Then swModelView.EnableGraphicsUpdate = True
        Exit Sub
    End If
    
    ' Traverse ve guncelle
    Dim processedParts As Object
    Set processedParts = CreateObject("Scripting.Dictionary")
    
    UpdateComponentProperties swRootComp, csvData, processedParts, swModel
    
    ' --- CSV'de olup montajda bulunmayan parcalar ---
    Dim csvKey As Variant
    For Each csvKey In csvData.Keys
        If Not processedParts.Exists(csvKey) Then
            notFoundCount = notFoundCount + 1
            detailLog = detailLog & "BULUNAMADI: " & csvKey & " (CSV'de var, montajda yok)" & vbCrLf
        End If
    Next csvKey
    
    ' --- GRAFIK AC ---
    If Not swModelView Is Nothing Then
        swModelView.EnableGraphicsUpdate = True
    End If
    
    ' --- SONUC ---
    Dim elapsed As Double
    elapsed = Timer - startTime
    If elapsed < 0 Then elapsed = elapsed + 86400
    
    Dim resultMsg As String
    resultMsg = "Custom Property Güncelleme Tamamlandi!" & vbCrLf & vbCrLf & _
                "Güncellenen: " & updatedCount & vbCrLf & _
                "Degisiklik Yok: " & skippedCount & vbCrLf & _
                "Montajda Bulunamadi: " & notFoundCount & vbCrLf & _
                "Hata: " & errorCount & vbCrLf & _
                "Süre: " & Round(elapsed, 1) & " saniye"
    
    If detailLog <> "" Then
        resultMsg = resultMsg & vbCrLf & vbCrLf & "--- DETAYLAR ---" & vbCrLf & detailLog
    End If
    
    MsgBox resultMsg, vbInformation, "Islem Tamam"
    
    ' Temizlik
    Set processedParts = Nothing
    Set csvData = Nothing
    Exit Sub

ErrorHandler:
    On Error Resume Next
    If Not swModelView Is Nothing Then swModelView.EnableGraphicsUpdate = True
    MsgBox "Hata olustu: " & Err.Description, vbCritical, "Makro Hatasi"
End Sub


' ============================================================================
' DOSYA SECME DIYALOGU
' ============================================================================
Function SelectCSVFile() As String
    Dim fd As Object
    Set fd = CreateObject("UserAccounts.CommonDialog")
    
    ' CommonDialog kullanılamıyorsa Shell ile
    Dim filePath As String
    filePath = InputBox( _
        "Google Sheets'ten indirilen CSV dosyasinin tam yolunu girin:" & vbCrLf & vbCrLf & _
        "Örnek: C:\Users\Kullanici\Desktop\SW_BOM_Export_20260317.csv", _
        "CSV Dosya Yolu", _
        CreateObject("WScript.Shell").SpecialFolders("Desktop") & "\")
    
    If filePath = "" Then
        SelectCSVFile = ""
        Exit Function
    End If
    
    ' Dosya var mi kontrol et
    If Dir(filePath) = "" Then
        MsgBox "Dosya bulunamadi: " & filePath, vbExclamation, "Hata"
        SelectCSVFile = ""
        Exit Function
    End If
    
    SelectCSVFile = filePath
End Function


' ============================================================================
' CSV OKUMA
' ============================================================================
Function ReadCSVFile(ByVal filePath As String) As Object
    Dim csvDict As Object
    Set csvDict = CreateObject("Scripting.Dictionary")
    
    ' UTF-8 okuma (ADODB.Stream)
    Dim stream As Object
    Set stream = CreateObject("ADODB.Stream")
    stream.Type = 2       ' adTypeText
    stream.Charset = "utf-8"
    stream.Open
    stream.LoadFromFile filePath
    
    Dim allText As String
    allText = stream.ReadText(-1)  ' adReadAll
    stream.Close
    Set stream = Nothing
    
    ' Satirlara ayir
    Dim lines() As String
    allText = Replace(allText, vbCrLf, vbLf)
    allText = Replace(allText, vbCr, vbLf)
    lines = Split(allText, vbLf)
    
    Dim i As Long
    Dim fields() As String
    
    ' Ilk satir baslik, atla
    For i = 1 To UBound(lines)
        If Trim(lines(i)) = "" Then GoTo NextLine
        
        fields = ParseCSVLine(lines(i), ";")
        
        If UBound(fields) >= CSV_TARIH Then
            Dim childRef As String
            childRef = Trim(fields(CSV_CHILD_REF))
            
            If childRef <> "" And Not csvDict.Exists(childRef) Then
                ' CP degerlerini diziye kaydet
                Dim cpValues(5) As String
                cpValues(0) = Trim(fields(CSV_URETIM_SEKLI))
                cpValues(1) = Trim(fields(CSV_MALZEME))
                cpValues(2) = Trim(fields(CSV_MALZEME_EBAT))
                cpValues(3) = Trim(fields(CSV_ALT_KOD))
                cpValues(4) = Trim(fields(CSV_REVIZYON))
                cpValues(5) = Trim(fields(CSV_TARIH))
                
                csvDict.Add childRef, cpValues
            End If
        End If
NextLine:
    Next i
    
    Set ReadCSVFile = csvDict
End Function


' ============================================================================
' CSV SATIR PARSE (basit tırnak destekli)
' ============================================================================
Function ParseCSVLine(ByVal line As String, ByVal delim As String) As String()
    Dim result() As String
    Dim fields As New Collection
    Dim inQuote As Boolean
    Dim current As String
    Dim c As Long
    Dim ch As String
    
    inQuote = False
    current = ""
    
    For c = 1 To Len(line)
        ch = Mid(line, c, 1)
        
        If ch = """" Then
            If inQuote And c < Len(line) And Mid(line, c + 1, 1) = """" Then
                current = current & """"
                c = c + 1  ' Cifte tirnagi atla (VBA For loop c'yi artirmaz, manuel artirmak lazim ama For'da olmaz)
                ' Not: VBA For/Next c degerini otomatik artirir, bu yuzden
                ' ikinci tirnagi current'e eklemek yeterli, c birden atlamaz.
                ' Düzeltme: Ekstra karaktrer eklenmis olacak, ikinci tirnak atlaniyor
            Else
                inQuote = Not inQuote
            End If
        ElseIf ch = delim And Not inQuote Then
            fields.Add current
            current = ""
        Else
            current = current & ch
        End If
    Next c
    
    fields.Add current
    
    ' Collection -> Array
    ReDim result(fields.count - 1)
    Dim idx As Long
    For idx = 1 To fields.count
        result(idx - 1) = fields(idx)
    Next idx
    
    ParseCSVLine = result
End Function


' ============================================================================
' BILESEN GUNCELLEME (RECURSIVE)
' ============================================================================
Sub UpdateComponentProperties(swComp As Object, csvData As Object, processedParts As Object, swModel As Object)
    Dim vChildComp As Variant
    Dim swChildComp As Object
    Dim childName As String
    Dim confName As String
    Dim i As Long
    
    On Error Resume Next
    vChildComp = swComp.GetChildren
    On Error GoTo 0
    
    If IsEmpty(vChildComp) Then Exit Sub
    
    For i = 0 To UBound(vChildComp)
        Set swChildComp = vChildComp(i)
        If swChildComp Is Nothing Then GoTo NextComp
        
        ' Suppressed mi?
        On Error Resume Next
        Dim isSuppressed As Boolean
        isSuppressed = swChildComp.isSuppressed
        If Err.Number <> 0 Then
            Err.Clear
            GoTo NextComp
        End If
        On Error GoTo 0
        
        If isSuppressed Then GoTo NextComp
        
        childName = GetComponentRef(swChildComp)
        
        On Error Resume Next
        confName = swChildComp.ReferencedConfiguration
        If Err.Number <> 0 Then
            confName = ""
            Err.Clear
        End If
        On Error GoTo 0
        
        ' Bu parcayi daha once islemis miydik?
        If Not processedParts.Exists(childName) Then
            processedParts.Add childName, True
            
            ' CSV'de var mi?
            If csvData.Exists(childName) Then
                Dim cpValues() As String
                cpValues = csvData(childName)
                
                ' Model referansini al
                Dim swMod As Object
                Set swMod = swChildComp.GetModelDoc2
                
                If Not swMod Is Nothing Then
                    Dim changed As Boolean
                    changed = False
                    
                    ' 6 CP'yi guncelle
                    changed = changed Or SetCP(swMod, confName, CP_URETIM_SEKLI, cpValues(0))
                    changed = changed Or SetCP(swMod, confName, CP_MALZEME, cpValues(1))
                    changed = changed Or SetCP(swMod, confName, CP_MALZEME_EBAT, cpValues(2))
                    changed = changed Or SetCP(swMod, confName, CP_ALT_KOD, cpValues(3))
                    changed = changed Or SetCP(swMod, confName, CP_REVIZYON, cpValues(4))
                    changed = changed Or SetCP(swMod, confName, CP_TARIH, cpValues(5))
                    
                    If changed Then
                        updatedCount = updatedCount + 1
                    Else
                        skippedCount = skippedCount + 1
                    End If
                Else
                    errorCount = errorCount + 1
                    detailLog = detailLog & "HATA: Model yüklenemedi: " & childName & vbCrLf
                End If
            End If
        End If
        
        ' Recursive: alt bilesenlere dal
        UpdateComponentProperties swChildComp, csvData, processedParts, swModel
        
NextComp:
    Next i
End Sub


' ============================================================================
' CUSTOM PROPERTY YAZMA
' ============================================================================
' CP degerini yazar. Degisiklik olduysa True doner.
Function SetCP(swMod As Object, confName As String, propName As String, newValue As String) As Boolean
    On Error Resume Next
    SetCP = False
    
    If swMod Is Nothing Then Exit Function
    
    Dim cpm As Object
    
    ' Oncelik: Konfigurasyon-spesifik, sonra genel
    ' Konfigurasyon varsa oraya yaz
    If confName <> "" Then
        Set cpm = swMod.Extension.CustomPropertyManager(confName)
    Else
        Set cpm = swMod.Extension.CustomPropertyManager("")
    End If
    
    If cpm Is Nothing Then
        Set cpm = swMod.Extension.CustomPropertyManager("")
    End If
    
    ' Mevcut degeri oku
    Dim existingVal As String
    Dim resolvedVal As String
    cpm.Get2 propName, existingVal, resolvedVal
    
    ' Karsilastir
    If Trim(resolvedVal) = Trim(newValue) Then
        SetCP = False
        Exit Function
    End If
    
    ' Farkli ise guncelle (veya yeni olustur)
    ' Set2 parametreleri: propName, fieldType, value, overwrite
    ' fieldType: 30 = swCustomInfoText
    Dim retVal As Long
    retVal = cpm.Set2(propName, newValue)
    
    ' Set2 basarisiz olduysa Add2 ile dene
    If retVal <> 0 Then
        ' Ilk once Add2 dene (yeni CP)
        cpm.Add3 propName, 30, newValue, 1  ' 1 = overwrite
    End If
    
    SetCP = True
End Function


' ============================================================================
' YARDIMCI FONKSIYONLAR
' ============================================================================
Function GetComponentRef(swComp As Object) As String
    On Error Resume Next
    Dim path As String
    Dim fileName As String
    
    path = swComp.GetPathName
    If path = "" Then
        fileName = swComp.Name2
        If InStr(fileName, "^") > 0 Then fileName = Left(fileName, InStr(fileName, "^") - 1)
    Else
        fileName = Mid(path, InStrRev(path, "\") + 1)
        If InStr(fileName, ".") > 0 Then fileName = Left(fileName, InStrRev(fileName, ".") - 1)
    End If
    GetComponentRef = fileName
End Function
