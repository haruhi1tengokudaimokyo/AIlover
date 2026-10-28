// Minimal read-only CLI over the official GARbro 1.5.44 libraries.
// GARbro is MIT licensed; its LICENSE.txt remains beside the official DLLs.
using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Text;
using System.Web.Script.Serialization;
using System.Security.Cryptography;
using System.Windows.Media.Imaging;
using GameRes;

class AmatsutsumiGarbro
{
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };
    static string Digest(byte[] bytes) {
        using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
    }
    static string SafeOutput(string root, string name) {
        root = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        var path = Path.GetFullPath(Path.Combine(root, name));
        if (!path.StartsWith(root, StringComparison.OrdinalIgnoreCase)) throw new Exception("Unsafe archive output path");
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        return path;
    }
    static void WriteLine(object data) { Console.WriteLine(Json.Serialize(data)); }

    [STAThread]
    static int Main(string[] args) {
        Console.OutputEncoding = new UTF8Encoding(false);
        try {
            if (args.Length < 2) throw new Exception("Usage: list ARCHIVE | extract ARCHIVE OUTPUT [PREFIX] | image ARCHIVE ENTRY OUTPUT.png");
            using (var db = File.OpenRead(Path.Combine(FormatCatalog.Instance.DataDirectory, "Formats.dat")))
                FormatCatalog.Instance.DeserializeScheme(db);
            var source = Path.GetFullPath(args[1]);
            if (args[0] == "image-batch") {
                if (args.Length != 4) throw new Exception("image-batch INPUTDIR OUTPUTDIR PATTERN");
                Directory.CreateDirectory(args[2]);
                foreach (var file in Directory.GetFiles(source, args[3]).OrderBy(x => x)) {
                    var output = Path.Combine(args[2], Path.GetFileNameWithoutExtension(file) + ".png");
                    if (File.Exists(output)) continue;
                    using (var input = VFS.OpenBinaryStream(file)) {
                        var image = ImageFormat.Read(input);
                        if (image == null) throw new Exception("Unknown image format");
                        var encoder = new PngBitmapEncoder();
                        encoder.Frames.Add(BitmapFrame.Create(image.Bitmap));
                        using (var stream = new FileStream(output, FileMode.CreateNew)) encoder.Save(stream);
                        WriteLine(new { entry = file, width = image.Width, height = image.Height });
                    }
                }
                return 0;
            }
            if (args[0] == "image-file") {
                using (var input = VFS.OpenBinaryStream(source)) {
                    var image = ImageFormat.Read(input);
                    if (image == null) throw new Exception("Unknown image format");
                    var encoder = new PngBitmapEncoder();
                    encoder.Frames.Add(BitmapFrame.Create(image.Bitmap));
                    var output = Path.GetFullPath(args[2]);
                    Directory.CreateDirectory(Path.GetDirectoryName(output));
                    using (var stream = new FileStream(output, FileMode.CreateNew)) encoder.Save(stream);
                    WriteLine(new { entry = source, width = image.Width, height = image.Height });
                }
                return 0;
            }
            if (args[0] == "image") {
                if (args.Length != 4) throw new Exception("image needs archive entry and output");
                VFS.ChDir(source);
                var entry = VFS.FindFile(args[2]);
                using (var decoder = VFS.OpenImage(entry)) {
                    var image = decoder.Image;
                    var encoder = new PngBitmapEncoder();
                    encoder.Frames.Add(BitmapFrame.Create(image.Bitmap));
                    var output = Path.GetFullPath(args[3]);
                    Directory.CreateDirectory(Path.GetDirectoryName(output));
                    using (var stream = new FileStream(output, FileMode.CreateNew)) encoder.Save(stream);
                    WriteLine(new { entry = entry.Name, width = image.Width, height = image.Height, format = decoder.SourceFormat.Tag });
                }
                return 0;
            }
            using (var archive = ArcFile.TryOpen(source)) {
                if (archive == null) throw new Exception("GARbro cannot open archive: " + FormatCatalog.Instance.LastError);
                foreach (var entry in archive.Dir) {
                    if (args.Length > 3 && !entry.Name.StartsWith(args[3], StringComparison.OrdinalIgnoreCase)) continue;
                    if (args[0] == "list") WriteLine(new { name = entry.Name, offset = entry.Offset, size = entry.Size, type = entry.Type, archive_format = archive.Tag });
                    else if (args[0] == "extract") {
                        if (args.Length < 3) throw new Exception("extract needs output directory");
                        byte[] bytes;
                        using (var input = archive.OpenEntry(entry)) using (var memory = new MemoryStream()) { input.CopyTo(memory); bytes = memory.ToArray(); }
                        var output = SafeOutput(args[2], entry.Name);
                        if (File.Exists(output)) { if (Digest(File.ReadAllBytes(output)) != Digest(bytes)) throw new Exception("Existing extracted file differs: " + output); }
                        else File.WriteAllBytes(output, bytes);
                        WriteLine(new { name = entry.Name, offset = entry.Offset, packed_bytes = entry.Size, bytes = bytes.Length, sha256 = Digest(bytes) });
                    }
                    else throw new Exception("Unknown operation");
                }
            }
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error.ToString()); return 1; }
    }
}
