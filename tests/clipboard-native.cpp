#include <QClipboard>
#include <QDragEnterEvent>
#include <QDropEvent>
#include <QGuiApplication>
#include <QInputMethodEvent>
#include <QMimeData>
#include <QQmlError>
#include <QQuickItem>
#include <QQuickView>
#include <QTest>
#include <cstdio>
#include <cstdlib>

class ClipboardOffer : public QMimeData {
public:
    QStringList formats() const override { return {QStringLiteral("text/plain")}; }
    bool hasFormat(const QString &format) const override { return formats().contains(format); }
protected:
    QVariant retrieveData(const QString &, QMetaType) const override {
        // Reading this offer would block or allocate attacker-controlled text.
        std::exit(90);
    }
};

static void require(bool condition, const char *message) {
    if (!condition) {
        std::fprintf(stderr, "%s\n", message);
        std::exit(1);
    }
}

int main(int argc, char **argv) {
    QGuiApplication application(argc, argv);
    require(argc == 2 || argc == 3, "Expected the QML fixture path");
    QQuickView window;
    window.setSource(QUrl::fromLocalFile(QString::fromLocal8Bit(argv[1])));
    for (const auto &error : window.errors()) qCritical().noquote() << error.toString();
    require(window.status() == QQuickView::Ready, "SearchField fixture did not load");
    window.show();
    require(QTest::qWaitForWindowExposed(&window), "SearchField window did not show");
    auto *field = window.rootObject()->findChild<QQuickItem *>(QStringLiteral("field"));
    require(field, "SearchField missing");
    field->forceActiveFocus();
    QTest::qWait(20);

    // Ownership changes and canPaste queries must inspect formats, never text.
    QGuiApplication::clipboard()->setMimeData(new ClipboardOffer);
    QTest::qWait(20);
    if (argc == 3) {
        QMetaObject::invokeMethod(field, "paste");
        require(false, "Native-paste control did not request clipboard text");
    }
    require(field->property("canPaste").toBool(), "Text offer was not recognized");
    for (char letter : QByteArray("jazz")) QTest::keyClick(&window, letter);
    require(field->property("text").toString() == QStringLiteral("jazz"), "Typing failed");
    QTest::keyClick(&window, Qt::Key_Left);
    QTest::keyClick(&window, Qt::Key_Backspace);
    require(field->property("text").toString() == QStringLiteral("jaz"), "Cursor editing failed");
    QTest::keyClick(&window, Qt::Key_Z, Qt::ControlModifier);
    require(field->property("text").toString() == QStringLiteral("jazz"), "Native undo failed");
    QTest::keyClick(&window, Qt::Key_A, Qt::ControlModifier);
    require(field->property("selectedText").toString() == QStringLiteral("jazz"), "Select all failed");
    QInputMethodEvent committed;
    committed.setCommitString(QString::fromUtf8("日本語 café"));
    QGuiApplication::sendEvent(field, &committed);
    require(field->property("text").toString() == QString::fromUtf8("日本語 café"), "IME commit failed");

    QObject *reader = nullptr;
    for (auto *child : field->findChildren<QObject *>()) {
        if (child->property("revision").isValid()) { reader = child; break; }
    }
    require(reader, "Bounded clipboard reader missing");
    for (auto key : {Qt::Key_V, Qt::Key_Insert}) {
        reader->setProperty("running", false);
        QTest::keyClick(&window, key, key == Qt::Key_V ? Qt::ControlModifier : Qt::ShiftModifier);
        require(reader->property("running").toBool(), "Paste bypassed the external reader");
        QMetaObject::invokeMethod(reader, "exited", Q_ARG(int, 1), Q_ARG(int, 0));
    }
    reader->setProperty("running", false);
    const QPoint point = field->mapToScene(QPointF(20, 15)).toPoint();
    QTest::mouseClick(&window, Qt::MiddleButton, Qt::NoModifier, point);
    require(reader->property("running").toBool(), "Primary paste bypassed the external reader");
    require(reader->property("command").toList().contains(QStringLiteral("--primary")), "Primary paste used the wrong selection");
    reader->setProperty("running", false);
    QMetaObject::invokeMethod(reader, "exited", Q_ARG(int, 1), Q_ARG(int, 0));
    QTest::mouseClick(&window, Qt::RightButton, Qt::NoModifier, point);
    QTest::keyClick(&window, Qt::Key_V, Qt::ControlModifier | Qt::ShiftModifier);
    QTest::keyClick(&window, Qt::Key_Menu);
    ClipboardOffer dropped;
    const QString beforeDrop = field->property("text").toString();
    QDragEnterEvent drag(point, Qt::CopyAction, &dropped, Qt::LeftButton, Qt::NoModifier);
    QGuiApplication::sendEvent(&window, &drag);
    QDropEvent drop(QPointF(point), Qt::CopyAction, &dropped, Qt::LeftButton, Qt::NoModifier);
    QGuiApplication::sendEvent(&window, &drop);
    require(!drag.isAccepted() && !drop.isAccepted(), "Search accepted an external drop");
    require(field->property("text").toString() == beforeDrop, "Drop changed search text");

    field->setProperty("text", QStringLiteral("abc"));
    QMetaObject::invokeMethod(field, "select", Q_ARG(int, 1), Q_ARG(int, 2));
    QTest::keyClick(&window, Qt::Key_V, Qt::ControlModifier);
    reader->setProperty("running", false);
    reader->setProperty("output", QString::fromUtf8("日本語"));
    QMetaObject::invokeMethod(reader, "exited", Q_ARG(int, 0), Q_ARG(int, 0));
    require(field->property("text").toString() == QString::fromUtf8("a日本語c"), "Bounded paste did not replace selection");
    QTest::keyClick(&window, Qt::Key_V, Qt::ControlModifier);
    QTest::keyClick(&window, 'x');
    const QString edited = field->property("text").toString();
    reader->setProperty("running", false);
    reader->setProperty("output", QStringLiteral("late"));
    QMetaObject::invokeMethod(reader, "exited", Q_ARG(int, 0), Q_ARG(int, 0));
    require(field->property("text").toString() == edited, "Late paste overwrote newer editing");

    // The native text engine retains selection, cut/copy, and input methods.
    field->setProperty("text", QString::fromUtf8("日本語 café"));
    QTest::keyClick(&window, Qt::Key_A, Qt::ControlModifier);
    QTest::keyClick(&window, Qt::Key_C, Qt::ControlModifier);
    require(QGuiApplication::clipboard()->text() == QString::fromUtf8("日本語 café"), "Copy failed");
    QTest::keyClick(&window, Qt::Key_X, Qt::ControlModifier);
    require(field->property("text").toString().isEmpty(), "Cut failed");

    const QString full = QString(63, QLatin1Char('a')) + QStringLiteral(" ending") + QString(58, QLatin1Char('z'));
    require(full.size() == 128, "Full query fixture has the wrong length");
    field->setProperty("text", full);
    field->setProperty("cursorPosition", 63);
    QTest::keyClick(&window, 'x');
    require(field->property("text").toString() == full, "Typing in a full query deleted its ending");
    require(field->property("cursorPosition").toInt() == 63, "Rejected input moved the cursor");
    QInputMethodEvent overflow;
    overflow.setCommitString(QString::fromUtf8("日本語"));
    QGuiApplication::sendEvent(field, &overflow);
    require(field->property("text").toString() == full, "IME input in a full query deleted its ending");
    QTest::keyClick(&window, Qt::Key_Backspace);
    require(field->property("text").toString().size() == 127, "Full queries cannot be shortened");
    const QString shortened = field->property("text").toString();
    QTest::keyClick(&window, 'x');
    require(field->property("text").toString().size() == 128, "Typing could not fill the query");
    QTest::keyClick(&window, 'y');
    QTest::keyClick(&window, Qt::Key_Z, Qt::ControlModifier);
    require(field->property("text").toString() == shortened, "Rejected overflow cleared earlier undo history");
    QTest::keyClick(&window, Qt::Key_Z, Qt::ControlModifier);
    require(field->property("text").toString() == full, "Undo after rejected input changed the query");
    QMetaObject::invokeMethod(field, "select", Q_ARG(int, 63), Q_ARG(int, 66));
    QInputMethodEvent replacement;
    replacement.setCommitString(QString::fromUtf8("日本語"));
    QGuiApplication::sendEvent(field, &replacement);
    require(field->property("text").toString() == full.left(63) + QString::fromUtf8("日本語") + full.mid(66),
            "A selection in a full query could not be replaced");
    field->setProperty("text", QString());
    for (int i = 0; i < 128; ++i) QTest::keyClick(&window, 'a');
    field->setProperty("cursorPosition", 63);
    QGuiApplication::sendEvent(field, &overflow);
    require(field->property("text").toString() == QString(128, QLatin1Char('a')),
            "Rejected IME input erased earlier typing");

    field->setProperty("text", QString(140, QLatin1Char('x')));
    require(field->property("text").toString().size() == 128, "Search length was not bounded");
    QTest::keyClick(&window, Qt::Key_End);
    QTest::qWait(20);
    require(field->property("cursorRectangle").toRectF().right() <= field->width(), "Long search cursor was clipped");
    QTest::keyClick(&window, Qt::Key_Home);
    QTest::qWait(20);
    require(field->property("cursorRectangle").toRectF().left() >= 0, "Search did not scroll back to the start");
    field->setProperty("text", QStringLiteral("a\nb\tc"));
    require(field->property("text").toString() == QStringLiteral("a b c"), "Search was not single line");
    QTest::keyClick(&window, Qt::Key_Tab);
    require(!field->hasActiveFocus(), "Tab did not leave search");
    qInfo("Native clipboard ownership, editing, IME, and paste routing passed");
    return 0;
}
